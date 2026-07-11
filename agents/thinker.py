"""Thinker — reads goal.md, writes plan.md."""
from __future__ import annotations

from typing import Any

from agents.base import AgentBlocked, AgentContext, BaseAgent
from core.parser import extract_blocked
from llm.normalizer import normalize_plan


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

    def write_output(self, ctx, model_output: str) -> str:
        # 1. Try to parse + validate via normalizer
        plan = normalize_plan(model_output)
        # 2. Serialize back to the plain-text format your parser expects
        if plan.is_blocked:
            raise AgentBlocked(plan.blocked_reason)
        serialized = []
        for t in plan.tasks:
            serialized.append(
                f"TASK {t.id}\nid: {t.id}\ntitle: {t.title}\n"
                f"description: {t.description}\ndepends_on: {t.depends_on}\n"
                f"acceptance_criteria: {t.acceptance_criteria}\n"
                f"needs_research: {str(t.needs_research).lower()}\nfiles: {t.files}\n"
            )
        plan_md = "\n".join(serialized)
        return str(self.state.write_md("plan", plan_md))
