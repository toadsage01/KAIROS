"""
Orchestrator — a DAG executor, NOT an LLM agent.

It does not "think". It does not "decide". It:
  1. Reads config/workflow.yaml -> DAG
  2. Reads state/tasks.json -> current position + pending task list
  3. Executes the next node:
     - agent node: instantiate agent, call run(ctx), advance
     - hitl node: write pending signal, return "paused"
     - branch node: parse review status, advance
     - terminal node: write tasks.json status=done, return "done"
  4. Writes state/tasks.json after every step (resumable)

It is resumable: if /run is called and tasks.json says we're paused at a
HITL gate, it checks the gate status. If approved, it advances. If still
pending, it returns "paused" again immediately.

The orchestrator processes ONE task at a time through the whole DAG.
The plan may contain N tasks; tasks.json tracks which task is current.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from agents.base import AgentBlocked, AgentContext, BaseAgent
from agents.thinker import ThinkerAgent
from agents.coder import CoderAgent
from agents.reviewer import ReviewerAgent
from agents.bugfixer import BugfixerAgent
from agents.researcher import ResearcherAgent
from core.dag import DAG
from core.hitl import HITLManager
from core.notify import notify_hitl_paused, notify_run_complete, notify_run_error
from core.state import FileState
from core.workspace import WorkspaceManager
from llm.router import load_agents
from memory.codemap import CodeMap
from memory.retriever import Indexer, Retriever
from memory.vectorstore import VectorStore

RunStatus = Literal["running", "paused", "done", "error"]

_AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "thinker": ThinkerAgent,
    "coder": CoderAgent,
    "reviewer": ReviewerAgent,
    "bugfixer": BugfixerAgent,
    "researcher": ResearcherAgent,
}


import json

def _parse_plan(plan_md: str) -> list[dict[str, Any]]:
    """Parse the thinker's plain-text output into a list of task dicts."""
    tasks: list[dict[str, Any]] = []
    
    # Match "TASK T1" (no markdown hashes)
    task_blocks = re.split(r"^TASK\s+(T\d+)", plan_md, flags=re.MULTILINE)
    
    for i in range(1, len(task_blocks), 2):
        task_id = task_blocks[i]
        block = task_blocks[i+1]
        
        task = {"id": task_id}
        
        # Updated regex: looks for "key: value" without the hyphen
        pattern = r"(\w+):\s*(.*?)(?=\n\w+:|\Z)"
        
        for match in re.finditer(pattern, block, re.DOTALL):
            k = match.group(1).strip()
            v = match.group(2).strip()
            
            if k == "id":
                continue  # We already have it from the header
            if k in ("needs_research",):
                task[k] = v.lower() == "true"
            elif k == "files":
                task[k] = v.strip().strip("\"'")
            else:
                task[k] = v
                
        if task.get("title"):
            tasks.append(task)
            
    return tasks

def _parse_review_status(review_md: str) -> str:
    """Return the review status from a review file."""
    # First check our injected header
    m = re.search(r"<!-- status: (\w+) -->", review_md)
    if m:
        return m.group(1).lower()
    # Fallback: first STATUS: line
    m = re.search(r"STATUS:\s*(\w+)", review_md, re.IGNORECASE)
    return m.group(1).lower() if m else "rejected"


def _is_meta_task(task: dict[str, Any], goal: str) -> bool:
    """Return True for tasks that are analysis/research/test chores, not edits."""
    title = str(task.get("title", "")).lower()
    description = str(task.get("description", "")).lower()
    text = f"{title} {description}"
    goal_l = goal.lower()

    if any(w in goal_l for w in ("test", "verify", "research", "analyze", "analyse")):
        return False

    meta_starts = (
        "analyze", "analyse", "examine", "investigate", "research",
        "review current", "test ", "verify ", "validate current",
    )
    return title.startswith(meta_starts) or (
        any(w in text for w in ("identify where", "validation gaps", "current structure"))
        and "implement" not in title
    )


def _single_source_file(repo_root: str) -> str:
    root = Path(repo_root)
    candidates: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file() or ".git" in p.parts or ".worktrees" in p.parts:
            continue
        if p.suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs"}:
            candidates.append(str(p.relative_to(root)))
    return candidates[0] if len(candidates) == 1 else ""


def _sanitize_tasks(tasks, goal, repo_root, max_tasks):
    REQUIRED = {"id", "title", "description", "acceptance_criteria"}
    clean = []
    default_file = _single_source_file(repo_root)
    for task in tasks:
        if not REQUIRED.issubset(task.keys()):
            continue  # ← reject malformed tasks instead of passing them through
        if _is_meta_task(task, goal):
            continue
        normalized = dict(task)
        # ... rest of existing logic
        if not str(normalized.get("files", "")).strip() and default_file:
            normalized["files"] = default_file
        normalized["needs_research"] = bool(normalized.get("needs_research")) and not default_file
        clean.append(normalized)
        if len(clean) >= max_tasks:
            break

    if clean:
        return clean

    return []


@dataclass
class RunState:
    """The state machine's persisted state, stored at state/tasks.json."""
    status: RunStatus = "running"
    current_task_index: int = 0
    current_node_id: str = "thinker"
    tasks: list[dict[str, Any]] = field(default_factory=list)
    review_iterations: dict[str, int] = field(default_factory=dict)
    last_error: str | None = None
    last_step_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "current_task_index": self.current_task_index,
            "current_node_id": self.current_node_id,
            "tasks": self.tasks,
            "review_iterations": self.review_iterations,
            "last_error": self.last_error,
            "last_step_at": self.last_step_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunState":
        return cls(
            status=d.get("status", "running"),
            current_task_index=d.get("current_task_index", 0),
            current_node_id=d.get("current_node_id", "thinker"),
            tasks=d.get("tasks", []),
            review_iterations=d.get("review_iterations", {}),
            last_error=d.get("last_error"),
            last_step_at=d.get("last_step_at", ""),
        )


class Orchestrator:
    def __init__(self,
                 state_dir: str = "./state",
                 config_dir: str = "./config"):
        self.state = FileState(state_dir)
        self.config_dir = config_dir
        self.dag = DAG.from_yaml(f"{config_dir}/workflow.yaml")
        self.agents_cfg = load_agents(f"{config_dir}/agents.yaml")
        self.hitl = HITLManager(self.state)
        self.workspace = WorkspaceManager(self.dag.target_repo)
        # Phase 3: vector store + codemap + retriever
        chroma_path = str(self.state.root.parent / ".chroma")
        self.vector = VectorStore(chroma_path)
        self.codemap = CodeMap(repo_root=self.dag.target_repo)
        self.retriever = Retriever(self.vector, self.codemap)
        self._indexed = False

    def _ensure_indexed(self) -> None:
        """Lazily index the target repo the first time the coder needs context."""
        if self._indexed:
            return
        try:
            indexer = Indexer(self.vector, self.codemap)
            stats = indexer.index_repo(self.dag.target_repo)
            self.state.append_log(
                f"indexed target_repo: {stats.get('files', 0)} files, "
                f"{stats.get('chunks', 0)} chunks (vector available={self.vector.available})"
            )
        except Exception as e:  # noqa: BLE001
            self.state.append_log(f"indexing failed (continuing without): {e}")
        self._indexed = True

    # ---------- public API ----------
    def start(self, goal: str) -> RunState:
        """Initialize a new run. Wipes state/tasks.json."""
        if not goal.strip():
            raise ValueError("goal must be non-empty")
        self.state.set_goal(goal)
        rs = RunState(status="running", current_node_id=self.dag.entry)
        self._persist(rs)
        self.state.append_log(f"run started: goal='{goal[:80]}'")
        return self.step()

    def step(self) -> RunState:
        """Execute nodes until we hit a HITL gate, terminal, or error.

        Returns status="paused" if we hit a HITL gate.
        Returns status="done" if we reached terminal.
        Returns status="error" on failure.

        Resumable: if called when already paused, checks gate status first.
        """
        rs = self._load()

        # Resuming from a paused state?
        if rs.status == "paused":
            node = self.dag.nodes.get(rs.current_node_id)
            if node and node.kind == "hitl":
                gate_status = self.hitl.status(node.gate)
                if gate_status == "approved":
                    rs.status = "running"
                    next_node = self.dag.next_node(rs.current_node_id, "approved")
                    if next_node:
                        rs.current_node_id = next_node.id
                        self._persist(rs)
                elif gate_status == "rejected":
                    rs.status = "error"
                    rs.last_error = f"HITL gate {node.gate} rejected"
                    self._persist(rs)
                    return rs
                else:
                    return rs  # still pending

        if rs.status in ("done", "error"):
            return rs

        # Loop: execute nodes until we pause/done/error
        while rs.status == "running":
            node = self.dag.nodes.get(rs.current_node_id)
            if node is None:
                rs.status = "error"
                rs.last_error = f"unknown node {rs.current_node_id}"
                break

            rs.last_step_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                rs = self._execute_node(rs, node)
            except AgentBlocked as e:
                rs.last_error = f"agent declined: {e.reason}"
                self.state.append_log(
                    f"agent declined at node={node.id}: {e.reason}"
                )
                break
            except Exception as e:  # noqa: BLE001
                rs.status = "error"
                rs.last_error = f"{type(e).__name__}: {e}"
                self.state.append_log(f"ERROR at node={node.id}: {e}")
                # Fire error notification
                try:
                    goal = self.state.get_goal() or ""
                    import re
                    m = re.search(r"^# Goal\n\n(.+?)(?:\n|$)", goal, re.DOTALL)
                    goal_text = m.group(1).strip() if m else goal[:200]
                    notify_run_error(goal_text, f"{type(e).__name__}: {e}")
                except Exception:
                    pass
                break
            self._persist(rs)

            # If the node we just executed was a HITL request, we're paused
            if rs.status == "paused":
                break
            # If we reached terminal, stop
            if rs.status == "done":
                break
            # Otherwise loop continues to next node

        self._persist(rs)
        return rs

    def approve(self, gate: str, decision: str = "approved", note: str = "") -> RunState:
        """Resolve a HITL gate, then run until the next pause/done/error."""
        self.hitl.resolve(gate, decision, note)
        return self.step()

    # ---------- internal ----------
    def _execute_node(self, rs: RunState, node) -> RunState:
        if node.kind == "terminal":
            rs.status = "done"
            self.state.append_log(f"run complete: tasks={len(rs.tasks)}")
            # Fire completion notification (Telegram, future channels)
            try:
                goal = self.state.get_goal() or ""
                import re
                m = re.search(r"^# Goal\n\n(.+?)(?:\n|$)", goal, re.DOTALL)
                goal_text = m.group(1).strip() if m else goal[:200]
                notify_run_complete(goal_text, len(rs.tasks), "done")
            except Exception:
                pass
            return rs

        if node.kind == "hitl":
            self.hitl.request(node.gate, payload={"node": node.id})
            rs.status = "paused"
            self.state.append_log(f"paused at HITL gate={node.gate}")
            # Fire HITL notification (Telegram, future channels)
            try:
                goal = self.state.get_goal() or ""
                import re
                m = re.search(r"^# Goal\n\n(.+?)(?:\n|$)", goal, re.DOTALL)
                goal_text = m.group(1).strip() if m else goal[:200]
                plan_md = self.state.read_md("plan") or "(no plan yet)"
                notify_hitl_paused(
                    gate=node.gate,
                    goal=goal_text,
                    plan_summary=plan_md[:800],
                )
            except Exception:
                pass
            return rs

        if node.kind == "branch":
            if not rs.tasks:
                rs.status = "error"
                rs.last_error = "branch node reached with no tasks"
                return rs
            task_id = rs.tasks[rs.current_task_index]["id"]
            review_md = self.state.read_md(task_id, subdir="review") or ""
            decision = _parse_review_status(review_md)
            routing_decision = "rejected" if decision == "unverifiable" else decision
            iters = rs.review_iterations.get(task_id, 0) + 1
            rs.review_iterations[task_id] = iters
            if decision != "approved":
                self.state.append_log(
                    f"task {task_id}: review decision={decision} "
                    f"(routing={routing_decision}) iteration={iters}"
                )
            if iters > self.dag.max_review_iterations and decision != "approved":
                self.state.append_log(
                    f"task {task_id}: max review iterations exceeded after "
                    f"{decision}, aborting worktree"
                )
                # Abort the worktree — its branch is discarded
                try:
                    self.workspace.for_task(task_id).abort()
                except Exception as e:  # noqa: BLE001
                    self.state.append_log(f"worktree abort failed: {e}")
                rs.status = "error"
                rs.last_error = (
                    f"task {task_id} {decision} after {iters} iterations"
                )
                return rs
            next_node = self.dag.next_node(node.id, routing_decision)
            if next_node is None:
                rs.status = "error"
                rs.last_error = f"no next node from branch {node.id}"
                return rs
            # On approval, merge the worktree's branch back to the target repo.
            if decision == "approved" and next_node.kind == "terminal":
                try:
                    sha = self.workspace.for_task(task_id).merge_to_target()
                    self.state.append_log(
                        f"task {task_id} approved; merged branch myforge/{task_id} "
                        f"-> target_repo (sha={sha[:8]})"
                )
                    self._indexed = False  # force re-index on next coder call
                    
                except Exception as e:  # noqa: BLE001
                    rs.status = "error"
                    rs.last_error = f"merge failed for task {task_id}: {e}"
                    return rs
            # Multi-task loop: if branch approved -> "done" AND we have more
            # tasks, advance task index and go back to coder for the next one.
            if (next_node.kind == "terminal" and decision == "approved"
                    and rs.current_task_index < len(rs.tasks) - 1):
                rs.current_task_index += 1
                rs.current_node_id = "coder"
                self.state.append_log(
                    f"task {task_id} approved; advancing to "
                    f"{rs.tasks[rs.current_task_index]['id']}"
                )
                return rs
            rs.current_node_id = next_node.id
            return rs

        if node.kind == "agent":
            return self._execute_agent(rs, node)

        rs.status = "error"
        rs.last_error = f"unknown node kind {node.kind}"
        return rs

    def _execute_agent(self, rs: RunState, node) -> RunState:
        agent_name = node.agent
        if agent_name not in _AGENT_CLASSES:
            rs.status = "error"
            rs.last_error = f"no agent class registered for {agent_name}"
            return rs

        # Thinker is special — it produces the task list, no per-task context
        if agent_name == "thinker":
            agent = _AGENT_CLASSES[agent_name](self.state, self.agents_cfg)
            ctx = AgentContext(task_id="plan", task=None, state=self.state)
            agent.run(ctx)
            # Parse plan.md into tasks
            plan_md = self.state.read_md("plan") or ""
            goal = self.state.get_goal() or ""
            rs.tasks = _sanitize_tasks(
                _parse_plan(plan_md),
                goal=goal,
                repo_root=self.dag.target_repo,
                max_tasks=self.dag.max_tasks_per_goal,
            )
            if not rs.tasks:
                rs.status = "error"
                rs.last_error = "thinker produced no executable tasks"
                self.state.append_log(rs.last_error)
                return rs
            self.state.append_log(f"thinker produced {len(rs.tasks)} tasks")
            rs.current_task_index = 0
            rs.current_node_id = node.next or "hitl_plan"
            return rs

        # All other agents operate on the current task
        if not rs.tasks:
            rs.status = "error"
            rs.last_error = f"agent {agent_name} invoked but no tasks exist"
            return rs
        if rs.current_task_index >= len(rs.tasks):
            rs.current_node_id = "done"
            return self._execute_node(rs, self.dag.nodes["done"])

        task = rs.tasks[rs.current_task_index]
        task_id = task["id"]

        # Conditional researcher insertion (Phase 4 hook)
        if agent_name == "coder" and task.get("needs_research"):
            research_path = self.state.read_md(task_id, subdir="research")
            if research_path is None:
                researcher = ResearcherAgent(self.state, self.agents_cfg)
                r_ctx = AgentContext(task_id=task_id, task=task, state=self.state)
                researcher.run(r_ctx)

        # Acquire (or reuse) a worktree for this task before coder/bugfixer/reviewer run.
        # The worktree is created lazily; coder writes files into it, reviewer
        # reads from it, bugfixer edits it. On approval, the branch handler
        # merges it back to the target repo.
        wt = None
        retrieval_ctx = ""
        if agent_name in ("coder", "reviewer", "bugfixer"):
            wt = self.workspace.for_task(task_id)
            wt.ensure()
            self.state.append_log(
                f"worktree ready task={task_id} path={wt.path}"
            )
            # Phase 3: ensure target repo is indexed, then retrieve bounded context
            if agent_name == "coder":
                self._ensure_indexed()
                try:
                    retrieval_ctx = self.retriever.retrieve(task)
                except Exception as e:  # noqa: BLE001
                    self.state.append_log(f"retrieval failed (continuing): {e}")
                    retrieval_ctx = ""

        agent = _AGENT_CLASSES[agent_name](self.state, self.agents_cfg)
        extra: dict[str, Any] = {
            "retry_count": rs.review_iterations.get(task_id, 0),
            "prior_rejection_count": rs.review_iterations.get(task_id, 0),
        }
        if retrieval_ctx:
            extra["retrieval"] = retrieval_ctx
        ctx = AgentContext(
            task_id=task_id, task=task, state=self.state,
            worktree=wt, extra=extra,
        )
        agent.run(ctx)

        # Advance to next node per the DAG
        if agent_name == "reviewer":
            rs.current_node_id = node.next or "review_check"
        elif agent_name == "coder":
            rs.current_node_id = node.next or "reviewer"
        elif agent_name == "bugfixer":
            rs.current_node_id = node.next or "reviewer"
        else:
            rs.current_node_id = node.next or "done"
        return rs

    def _persist(self, rs: RunState) -> None:
        self.state.write_json("tasks", rs.to_dict())

    def _load(self) -> RunState:
        d = self.state.read_json("tasks")
        if d is None:
            return RunState(status="running", current_node_id=self.dag.entry)
        return RunState.from_dict(d)
