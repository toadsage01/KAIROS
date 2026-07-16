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
from tools.registry import get_tool_registry

RunStatus = Literal["running", "paused", "done", "error"]

_AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "thinker": ThinkerAgent,
    "coder": CoderAgent,
    "reviewer": ReviewerAgent,
    "bugfixer": BugfixerAgent,
    "researcher": ResearcherAgent,
}


def _parse_plan(plan_md: str) -> list[dict[str, Any]]:
    """Parse the thinker's plan.md into a list of task dicts.
    
    Handles ALL formats SOTA models produce:
      - "## Task T1" with "- key: value" lines (original)
      - "TASK T1" with "key: value" lines (Codex)
      - "TASK 1" with "key: value" lines (DeepSeek/SOTA — no T prefix)
      - "## Task 1" with "- key: value" lines (mixed)
    
    Normalizes all task IDs to "T1", "T2", etc. internally for consistency.
    """
    tasks: list[dict[str, Any]] = []
    
    # Match "TASK <id>" or "## Task <id>" where <id> is ANY non-whitespace token.
    # SOTA models produce creative IDs: T1, 1, M0, image-search, wireframe, etc.
    # We accept anything that's not whitespace, then normalize later.
    task_blocks = re.split(r"(?:^|\n)(?:##\s*)?TASK\s+(\S+)\s*", plan_md, flags=re.IGNORECASE)
    
    if len(task_blocks) > 1:
        for i in range(1, len(task_blocks), 2):
            raw_id = task_blocks[i].strip()
            # Keep the original ID as-is (SOTA models produce M0, image-search, etc.)
            # Only normalize purely numeric IDs: "1" → "T1"
            if raw_id.isdigit():
                task_id = f"T{raw_id}"
            else:
                task_id = raw_id
            block = task_blocks[i + 1]
            task: dict[str, Any] = {"id": task_id}
            
            # Parse "key: value" pairs. The SOTA model may put them on
            # separate lines OR all on one line. This pattern handles both:
            #   - "id: 1\ntitle: Setup..."  (separate lines)
            #   - "id: 1 title: Setup..."   (single line, space-separated)
            # The lookahead checks for the next "word:" pattern.
            pattern = r"(\w+):\s*(.*?)(?=\s+(?:\w+:)|\Z)"
            for match in re.finditer(pattern, block, re.DOTALL):
                k = match.group(1).strip()
                v = match.group(2).strip()
                if k.lower() == "id":
                    # Override the normalized ID with the actual value if present,
                    # but keep it normalized to T<n> format
                    continue
                if k.lower() in ("needs_research",):
                    task["needs_research"] = v.lower() == "true"
                elif k.lower() == "files":
                    task["files"] = v.strip().strip("\"'").strip()
                elif k.lower() == "depends_on":
                    # Parse list format: ['1', '2'] or [1, 2] or 1,2
                    deps = v.strip()
                    if deps.startswith("["):
                        deps = deps.strip("[]")
                    dep_list = [d.strip().strip("'\"") for d in deps.split(",") if d.strip()]
                    # Keep dep IDs as-is (SOTA models use M0, image-search, etc.)
                    # Only normalize purely numeric deps: "1" → "T1"
                    task["depends_on"] = [
                        f"T{d}" if d.isdigit() else d
                        for d in dep_list
                    ]
                else:
                    task[k.lower()] = v
            
            if task.get("title"):
                tasks.append(task)
        
        if tasks:
            return tasks
    
    # Fallback: try "## Task T1" with "- key: value" lines (original format)
    blocks = re.split(r"^## Task\s+", plan_md, flags=re.MULTILINE)
    for blk in blocks[1:]:
        lines = blk.strip().splitlines()
        if not lines:
            continue
        raw_id = lines[0].strip()
        task_id = raw_id if raw_id.upper().startswith("T") else f"T{raw_id}"
        task = {"id": task_id}
        for ln in lines[1:]:
            m = re.match(r"^-\s+(\w+):\s*(.*)$", ln)
            if m:
                k, v = m.group(1), m.group(2).strip()
                if k in ("needs_research",):
                    task[k] = v.lower() == "true"
                else:
                    task[k] = v
        if task.get("title") or task.get("id"):
            tasks.append(task)
    return tasks


def _parse_review_status(review_md: str) -> str:
    """Return 'approved' or 'rejected' from a review file."""
    # First check our injected header
    m = re.search(r"<!-- status: (\w+) -->", review_md)
    if m:
        return m.group(1).lower()
    # Fallback: first STATUS: line
    m = re.search(r"STATUS:\s*(\w+)", review_md, re.IGNORECASE)
    return m.group(1).lower() if m else "rejected"


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
        # Batch 3: tool registry + per-run workspace
        self.tool_registry = get_tool_registry()
        self.workspace_path: Path = Path(self.dag.target_repo)

    def _ensure_indexed(self) -> None:
        """Lazily index the target repo the first time the coder needs context."""
        if self._indexed:
            return
        try:
            indexer = Indexer(self.vector, self.codemap)
            stats = indexer.index_repo(str(self.workspace_path))
            self.state.append_log(
                f"indexed workspace: {stats.get('files', 0)} files, "
                f"{stats.get('chunks', 0)} chunks (vector available={self.vector.available})"
            )
        except Exception as e:  # noqa: BLE001
            self.state.append_log(f"indexing failed (continuing without): {e}")
        self._indexed = True

    # ---------- public API ----------
    def start(self, goal: str, workspace_path: str | None = None) -> RunState:
        """Initialize a new run. Wipes state/tasks.json.

        Args:
            goal: The task goal
            workspace_path: Optional path to the target repo for this run.
                           If None, uses MYFORGE_TARGET_REPO from env.
        """
        if not goal.strip():
            raise ValueError("goal must be non-empty")
        # Batch 3: per-run workspace
        if workspace_path:
            self.workspace_path = Path(workspace_path).resolve()
            self.workspace = WorkspaceManager(str(self.workspace_path))
            self.codemap.repo_root = str(self.workspace_path)
            self._indexed = False  # force re-index for new workspace
            self.state.append_log(f"workspace set: {self.workspace_path}")
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
                # Agent declined via <blocked> tag. Treat as task failure.
                rs.status = "error"
                rs.last_error = f"agent blocked: {e.reason}"
                self.state.append_log(
                    f"agent blocked at node={node.id}: {e.reason}"
                )
                # If this is a bugfixer block, the task is unrecoverable.
                # The human should review the plan or rephrase the goal.
                # Fire error notification so the user knows.
                try:
                    goal = self.state.get_goal() or ""
                    import re
                    m = re.search(r"^# Goal\n\n(.+?)(?:\n|$)", goal, re.DOTALL)
                    goal_text = m.group(1).strip() if m else goal[:200]
                    notify_run_error(
                        goal_text,
                        f"Agent blocked at {node.id}: {e.reason}. "
                        f"Task may be too ambiguous — try rephrasing the goal."
                    )
                except Exception:
                    pass
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
                # Extract just the goal text from the markdown
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
            iters = rs.review_iterations.get(task_id, 0) + 1
            rs.review_iterations[task_id] = iters
            if iters > self.dag.max_review_iterations and decision == "rejected":
                self.state.append_log(
                    f"task {task_id}: max review iterations exceeded, aborting worktree"
                )
                # Abort the worktree — its branch is discarded
                try:
                    self.workspace.for_task(task_id).abort()
                except Exception as e:  # noqa: BLE001
                    self.state.append_log(f"worktree abort failed: {e}")
                rs.status = "error"
                rs.last_error = f"task {task_id} rejected after {iters} iterations"
                return rs
            next_node = self.dag.next_node(node.id, decision)
            if next_node is None:
                rs.status = "error"
                rs.last_error = f"no next node from branch {node.id}"
                return rs
            # On approval, merge the worktree's branch back to the target repo.
            if decision == "approved" and next_node.id in ("done",):
                try:
                    sha = self.workspace.for_task(task_id).merge_to_target()
                    self.state.append_log(
                        f"task {task_id} approved; merged branch myforge/{task_id} "
                        f"-> target_repo (sha={sha[:8]})"
                    )
                except Exception as e:  # noqa: BLE001
                    rs.status = "error"
                    rs.last_error = f"merge failed for task {task_id}: {e}"
                    return rs
            # Multi-task loop: if branch approved -> "done" AND we have more
            # tasks, advance task index and go back to coder for the next one.
            if (next_node.id == "done" and decision == "approved"
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
            # /btw integration for thinker
            btw_notes = self._read_btw_queue()
            thinker_extra = {"btw_notes": btw_notes} if btw_notes else None
            if btw_notes:
                self.state.append_log(
                    f"btw: injecting {len(btw_notes)} side note(s) into thinker"
                )
            ctx = AgentContext(
                task_id="plan", task=None, state=self.state,
                extra=thinker_extra,
            )
            agent.run(ctx)
            # Parse plan.md into tasks
            plan_md = self.state.read_md("plan") or ""
            rs.tasks = _parse_plan(plan_md)
            
            # Layer 2 fallback: if regex parser returned 0 tasks, try the
            # normalizer (Groq + instructor) to reformat SOTA output
            if not rs.tasks and plan_md.strip():
                self.state.append_log("parser returned 0 tasks — trying normalizer")
                try:
                    from llm.normalizer import normalize_plan
                    plan_obj = normalize_plan(plan_md)
                    # Convert Plan pydantic object to list of dicts
                    if hasattr(plan_obj, "tasks") and plan_obj.tasks:
                        rs.tasks = []
                        for t in plan_obj.tasks:
                            task_dict = {
                                "id": t.id,
                                "title": t.title,
                                "description": t.description,
                                "needs_research": getattr(t, "needs_research", False),
                                "files": getattr(t, "files", ""),
                                "acceptance_criteria": getattr(t, "acceptance_criteria", ""),
                            }
                            if hasattr(t, "depends_on") and t.depends_on:
                                task_dict["depends_on"] = t.depends_on
                            rs.tasks.append(task_dict)
                        self.state.append_log(
                            f"normalizer recovered {len(rs.tasks)} tasks"
                        )
                except Exception as e:  # noqa: BLE001
                    self.state.append_log(f"normalizer failed: {e}")
            
            # Dynamic task cap: SOTA models ignore prompt caps, so enforce here.
            # Instead of a fixed number, cap based on goal complexity:
            #   - Goals under 30 words: max 2 tasks
            #   - Goals under 80 words: max 4 tasks
            #   - Goals over 80 words: max 6 tasks
            #   - Hard ceiling: 8 tasks (prevents runaway decomposition)
            # This adapts to different project sizes without being too restrictive.
            goal_text = self.state.get_goal() or ""
            # Extract just the goal text from the markdown
            import re as _re
            goal_match = _re.search(r"^# Goal\n\n(.+?)(?:\n|$)", goal_text, _re.DOTALL)
            goal_clean = goal_match.group(1).strip() if goal_match else goal_text
            goal_word_count = len(goal_clean.split())
            
            if goal_word_count < 30:
                max_tasks = 2
            elif goal_word_count < 80:
                max_tasks = 4
            else:
                max_tasks = 6
            
            # Hard ceiling
            max_tasks = min(max_tasks, 8)
            
            if len(rs.tasks) > max_tasks:
                original_count = len(rs.tasks)
                rs.tasks = rs.tasks[:max_tasks]
                self.state.append_log(
                    f"hard-capped {original_count} tasks to {max_tasks} "
                    f"(SOTA model ignored prompt cap)"
                )
            
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
        # Batch 3: set use_tools + allowed_tools from config
        agent_cfg = self.agents_cfg.get(agent_name)
        if agent_cfg and hasattr(agent, "use_tools"):
            agent.use_tools = agent_cfg.use_tools
            agent.allowed_tools = agent_cfg.allowed_tools or []

        # /btw integration: check for queued side questions
        # These are notes the user typed via Ctrl+T in the TUI while
        # the agent was running. They get injected into the next prompt.
        btw_notes = self._read_btw_queue()
        extra: dict[str, Any] = {}
        if retrieval_ctx:
            extra["retrieval"] = retrieval_ctx
        if btw_notes:
            extra["btw_notes"] = btw_notes
            self.state.append_log(
                f"btw: injecting {len(btw_notes)} side note(s) into {agent_name}"
            )

        ctx = AgentContext(
            task_id=task_id, task=task, state=self.state,
            worktree=wt,
            extra=extra if extra else None,
            tool_registry=self.tool_registry,
            workspace_path=self.workspace_path,
            use_tools=getattr(agent, "use_tools", False),
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

    def _read_btw_queue(self) -> list[str]:
        """Read and clear the /btw side question queue.

        The TUI writes notes to state/btw_queue.json when the user
        presses Ctrl+T. This method reads them, clears the file,
        and returns the list of note strings.

        Returns:
            List of user notes to inject into the next agent prompt.
        """
        import json as _json
        from pathlib import Path

        btw_path = self.state.root / "btw_queue.json"
        if not btw_path.exists():
            return []

        try:
            data = _json.loads(btw_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            notes = [item.get("message", "") for item in data if item.get("message")]
            # Clear the queue after reading
            btw_path.write_text("[]", encoding="utf-8")
            return notes
        except Exception:
            return []
