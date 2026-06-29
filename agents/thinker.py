"""Thinker — reads goal.md, writes plan.md."""
from __future__ import annotations

from agents.base import AgentContext, BaseAgent


class ThinkerAgent(BaseAgent):
    name = "thinker"

    def build_prompt(self, ctx: AgentContext) -> str:
        goal = self.state.get_goal() or "(no goal set)"
        return (
            "Read the following goal and produce a plan.md per the format in "
            "your system prompt.\n\n"
            f"--- goal.md ---\n{goal}\n--- end ---\n"
        )

    def write_output(self, ctx: AgentContext, model_output: str) -> str:
        path = self.state.write_md("plan", model_output)
        return str(path)
