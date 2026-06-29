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

    def run(self, ctx: AgentContext) -> str:
        """One LLM call. Writes output. Returns the state file path."""
        prompt = self.build_prompt(ctx)
        out = route(
            agent_name=self.name,
            prompt=prompt,
            agents=self.agents_cfg,
            extra_context=self.extra_context(ctx),
        )
        path = self.write_output(ctx, out)
        self.state.append_log(
            f"agent={self.name} task={ctx.task_id} wrote={path}"
        )
        return path
