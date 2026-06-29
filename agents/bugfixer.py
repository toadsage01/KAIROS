"""Bugfixer — reads review + changes + worktree files, writes new
changes/{task_id}.md and updates files in the worktree."""
from __future__ import annotations

from agents.base import AgentContext, BaseAgent
from core.parser import parse_coder_output


def _looks_like_placeholder_path(path: str, existing: list[str]) -> bool:
    cleaned = path.strip().strip("\"'")
    if not cleaned:
        return True
    return cleaned == "main.py" and cleaned not in existing


def _single_existing_source(existing: list[str]) -> str | None:
    candidates = [
        f for f in existing
        if f.endswith(".py") and f.strip().strip("\"'") and not f.startswith(".")
    ]
    return candidates[0] if len(candidates) == 1 else None


class BugfixerAgent(BaseAgent):
    name = "bugfixer"

    def build_prompt(self, ctx: AgentContext) -> str:
        task = ctx.task or {}
        changes = self.state.read_md(ctx.task_id, subdir="changes") or ""
        review = self.state.read_md(ctx.task_id, subdir="review") or ""
        parts = [
            f"Apply the reviewer's defect list to the coder's output for task {ctx.task_id}.",
            f"\nTask title: {task.get('title', '')}",
            f"\n--- changes/{ctx.task_id}.md (current coder output) ---\n{changes}\n--- end ---",
            f"\n--- review/{ctx.task_id}.md ---\n{review}\n--- end ---",
        ]
        # Show the bugfixer the ACTUAL current content of files in the worktree
        if ctx.worktree is not None:
            existing = ctx.worktree.list_files()
            if existing:
                parts.append(
                    "\n--- current files in worktree (preserve existing functionality) ---"
                )
                for f in existing[:20]:
                    try:
                        content = ctx.worktree.read_file(f) or ""
                        lang = f.rsplit(".", 1)[-1] if "." in f else "text"
                        parts.append(f"\n### {f}\n```{lang}\n{content}\n```")
                    except Exception:
                        parts.append(f"\n### {f} (could not read)")
                parts.append("\n--- end of current files ---")
        return "\n".join(parts)

    def write_output(self, ctx: AgentContext, model_output: str) -> str:
        path = self.state.write_md(ctx.task_id, model_output, subdir="changes")
        if ctx.worktree is not None:
            blocks = parse_coder_output(model_output, task=ctx.task, task_id=ctx.task_id)
            if not blocks:
                raise ValueError("bugfixer output did not contain any writable code blocks")
            existing = ctx.worktree.list_files()
            single_source = _single_existing_source(existing)
            for blk in blocks:
                if single_source and _looks_like_placeholder_path(blk.path, existing):
                    blk.path = single_source
                ctx.worktree.write_file(blk.path, blk.content)
            ctx.worktree.commit(f"myforge: bugfixer pass for {ctx.task_id}")
            self.state.append_log(
                f"bugfixer task={ctx.task_id} wrote {len(blocks)} file(s) to worktree"
            )
        return str(path)
