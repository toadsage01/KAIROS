"""Reviewer — reads changes/{task_id}.md audit + real files from worktree,
writes review/{task_id}.md."""
from __future__ import annotations

import re
from typing import Any

from agents.base import AgentContext, BaseAgent


class ReviewerAgent(BaseAgent):
    name = "reviewer"

    def template_vars(self, ctx: AgentContext) -> dict[str, Any]:
        vars_ = super().template_vars(ctx)
        changes = self.state.read_md(ctx.task_id, subdir="changes") or ""
        vars_["coder_response_or_diff"] = changes[:4000]
        if ctx.worktree is not None:
            vars_["relevant_file_tree_or_ast_summary"] = "\n".join(
                ctx.worktree.list_files()[:50]
            )
        return vars_

    def build_prompt(self, ctx: AgentContext) -> str:
        task = ctx.task or {}
        prior_rejection_count = 0
        if ctx.extra:
            prior_rejection_count = int(
                ctx.extra.get("prior_rejection_count",
                              ctx.extra.get("retry_count", 0)) or 0
            )
        changes = self.state.read_md(ctx.task_id, subdir="changes") or ""
        parts = [
            f"Review the coder's output for task {ctx.task_id}.",
            f"\nTask title: {task.get('title', '')}",
            f"Task description: {task.get('description', '')}",
            f"Prior rejection count: {prior_rejection_count}",
            f"\n--- changes/{ctx.task_id}.md (audit record) ---\n{changes}\n--- end ---",
        ]
        # Also show the actual files written to the worktree
        if ctx.worktree is not None:
            files = ctx.worktree.list_files()
            if files:
                parts.append("\n--- files in worktree ---")
                for f in files[:20]:
                    content = ctx.worktree.read_file(f) or ""
                    parts.append(f"\n```{f.rsplit('.', 1)[-1] if '.' in f else 'text'} path={f}")
                    parts.append(content[:2000])
                    parts.append("```")
                parts.append("--- end ---")
        return "\n".join(parts)

    def write_output(self, ctx: AgentContext, model_output: str) -> str:
        m = re.search(r"STATUS:\s*(approved|rejected|unverifiable)",
                      model_output, re.IGNORECASE)
        status = m.group(1).lower() if m else "rejected"
        header = f"<!-- status: {status} -->\n"
        path = self.state.write_md(
            ctx.task_id, header + model_output, subdir="review"
        )
        return str(path)
