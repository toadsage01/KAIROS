"""
Agent base class. An agent is exactly:
  - one LLM call via llm.router.route()
  - bounded input from state files
  - bounded output to one state file

There is NO framework. No LangChain. No CrewAI. No "agent as a service".
A subclass implements `build_prompt()` and `write_output()`. That's it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from core.state import FileState
from core.workspace import Worktree
from llm.router import AgentConfig, route, load_agents


class AgentBlocked(Exception):
    """Raised when a model explicitly declines to proceed via <blocked>."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class AgentContext:
    """Bounded input passed to an agent invocation."""
    task_id: str
    task: dict[str, Any] | None  # parsed task from plan.md
    state: FileState
    worktree: Worktree | None = None  # set for coder/reviewer/bugfixer
    extra: dict[str, Any] | None = None


class BaseAgent(ABC):
    name: str = "base"

    def __init__(self, state: FileState,
                 agents_cfg: dict[str, AgentConfig] | None = None):
        self.state = state
        self.agents_cfg = agents_cfg or load_agents()

    @abstractmethod
    def build_prompt(self, ctx: AgentContext) -> str:
        """Return the user prompt for this agent."""
        ...

    @abstractmethod
    def write_output(self, ctx: AgentContext, model_output: str) -> str:
        """Persist the model output to state. Returns the state file path."""
        ...

    def extra_context(self, ctx: AgentContext) -> str:
        """Optional extra context injected into the system prompt."""
        return ""

    def template_vars(self, ctx: AgentContext) -> dict[str, Any]:
        """Variables used to render the agent's system prompt template."""
        task = ctx.task or {}
        extra = ctx.extra or {}
        title = str(task.get("title", ""))
        description = str(task.get("description", ""))
        acceptance = str(task.get("acceptance_criteria", ""))
        files = str(task.get("files", ""))
        task_description = "\n".join(
            part for part in (
                f"Title: {title}" if title else "",
                f"Description: {description}" if description else "",
                f"Files: {files}" if files else "",
            ) if part
        )
        return {
            "task_id": ctx.task_id,
            "state_md_content": "",
            "specific_goal_or_phase": "",
            "compressed_state_md_slice": "",
            "relevant_file_tree_or_ast_summary": "",
            "existing_dependencies_or_stack_summary": "",
            "specific_task_description": task_description,
            "bullet_list_of_done_conditions": acceptance,
            "coder_response_or_diff": "",
            "coder_response_or_current_files": "",
            "reviewer_rejection_list": "",
            "prior_rejection_count": extra.get("prior_rejection_count", 0),
            "prior_fix_attempt_count": extra.get("retry_count", 0),
        }

    def run(self, ctx: AgentContext) -> str:
        """One LLM call. Writes output. Returns the state file path."""
        prompt = self.build_prompt(ctx)
        out = route(
            agent_name=self.name,
            prompt=prompt,
            agents=self.agents_cfg,
            extra_context=self.extra_context(ctx),
            template_vars=self.template_vars(ctx),
        )
        path = self.write_output(ctx, out)
        self.state.append_log(
            f"agent={self.name} task={ctx.task_id} wrote={path}"
        )
        return path
