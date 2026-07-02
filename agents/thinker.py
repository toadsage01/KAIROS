"""Thinker — reads goal.md, writes plan.md."""
from __future__ import annotations

from typing import Any

from agents.base import AgentBlocked, AgentContext, BaseAgent
from core.parser import extract_blocked


class ThinkerAgent(BaseAgent):
    name = "thinker"

    def build_prompt(self, ctx: AgentContext) -> str:
        goal = self.state.get_goal() or "(no goal set)"
        return (
            "Read the following goal and produce a plan.md per the format in "
            "your system prompt.\n\n"
            f"--- goal.md ---\n{goal}\n--- end ---\n"
        )

    def template_vars(self, ctx: AgentContext) -> dict[str, Any]:
        vars_ = super().template_vars(ctx)
        goal = self.state.get_goal() or ""
        vars_.update({
            "state_md_content": goal,
            "specific_goal_or_phase": goal,
        })
        return vars_

    def write_output(self, ctx: AgentContext, model_output: str) -> str:
        blocked = extract_blocked(model_output)
        if blocked:
            raise AgentBlocked(blocked)

        path = self.state.write_md("plan", model_output)
        return str(path)
