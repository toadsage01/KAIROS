"""Reviewer — reads changes/{task_id}.md audit + real files from worktree,
writes review/{task_id}.md."""
from __future__ import annotations

import re
from agents.base import AgentContext, BaseAgent


class ReviewerAgent(BaseAgent):
    name = "reviewer"

    def build_prompt(self, ctx: AgentContext) -> str:
        task = ctx.task or {}
        changes = self.state.read_md(ctx.task_id, subdir="changes") or ""
        parts = [
            f"Review the coder's output for task {ctx.task_id}.",
            f"\nTask title: {task.get('title', '')}",
            f"Task description: {task.get('description', '')}",
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
        m = re.search(r"STATUS:\s*(approved|rejected)",
                      model_output, re.IGNORECASE)
        status = m.group(1).lower() if m else "rejected"
        header = f"<!-- status: {status} -->\n"
        path = self.state.write_md(
            ctx.task_id, header + model_output, subdir="review"
        )
        return str(path)
