"""Coder — reads task from plan.md, writes changes/{task_id}.md audit
record AND writes real files into the per-task worktree."""
from __future__ import annotations

from typing import Any

from agents.base import AgentBlocked, AgentContext, BaseAgent
from core.parser import extract_blocked, parse_coder_output


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


class CoderAgent(BaseAgent):
    name = "coder"

    def template_vars(self, ctx: AgentContext) -> dict[str, Any]:
        vars_ = super().template_vars(ctx)
        task = ctx.task or {}
        
        # Map the task dictionary to the Jinja variables in coder.j2
        vars_["task_id"] = ctx.task_id
        vars_["specific_task_description"] = task.get("description", "No description provided.")
        vars_["bullet_list_of_done_conditions"] = task.get("acceptance_criteria", "No criteria provided.")
        
        if ctx.extra and ctx.extra.get("retrieval"):
            vars_["compressed_state_md_slice"] = ctx.extra["retrieval"]
            vars_["relevant_file_tree_or_ast_summary"] = ctx.extra["retrieval"]
        return vars_

    def build_prompt(self, ctx: AgentContext) -> str:
        task = ctx.task or {}
        research = self.state.read_md(ctx.task_id, subdir="research") or ""
        parts = [
            f"Implement task {ctx.task_id}.",
            f"Title: {task.get('title', '')}",
            f"Description: {task.get('description', '')}",
            f"Files to touch: {task.get('files', '') or '(unspecified)'}",
        ]
        # Phase 3: bounded retrieval context (vector + repo map)
        if ctx.extra and ctx.extra.get("retrieval"):
            parts.append(f"\n--- retrieval context ---\n{ctx.extra['retrieval']}\n--- end ---")
        if research:
            parts.append(f"\n--- research/{ctx.task_id}.md ---\n{research[:2000]}\n--- end ---")
        # Show the coder the ACTUAL current content of files in the worktree.
        # This is the ground truth — more reliable than the vector store, which
        # may be stale after previous merges.
        if ctx.worktree is not None:
            existing = ctx.worktree.list_files()
            if existing:
                parts.append(
                    "\n--- current files in worktree (DO NOT lose any of this) ---"
                )
                for f in existing[:20]:  # cap at 20 files
                    try:
                        content = ctx.worktree.read_file(f) or ""
                        lang = f.rsplit(".", 1)[-1] if "." in f else "text"
                        parts.append(f"\n### {f}\n```{lang}\n{content}\n```")
                    except Exception:
                        parts.append(f"\n### {f} (could not read)")
                parts.append("\n--- end of current files ---")
                parts.append(
                    "\nIMPORTANT: When modifying an existing file, output the COMPLETE "
                    "new file with ALL existing functions preserved plus your changes. "
                    "Do NOT remove existing functionality."
                )
        return "\n".join(parts)

    def write_output(self, ctx: AgentContext, model_output: str) -> str:
        blocked = extract_blocked(model_output)
        if blocked:
            raise AgentBlocked(blocked)

        # 1. Always write the audit record to state/changes/{task_id}.md
        path = self.state.write_md(ctx.task_id, model_output, subdir="changes")
        # 2. Parse fenced blocks with path= headers and write real files
        if ctx.worktree is not None:
            blocks = parse_coder_output(model_output, task=ctx.task, task_id=ctx.task_id)
            if not blocks:
                raise ValueError("coder output did not contain any writable code blocks")
            existing = ctx.worktree.list_files()
            single_source = _single_existing_source(existing)
            for blk in blocks:
                if single_source and _looks_like_placeholder_path(blk.path, existing):
                    blk.path = single_source
                if blk.action == "delete":
                    ctx.worktree.delete_file(blk.path)
                else:
                    ctx.worktree.write_file(blk.path, blk.content)
            ctx.worktree.commit(f"myforge: coder output for {ctx.task_id}")
            self.state.append_log(
                f"coder task={ctx.task_id} wrote {len(blocks)} file(s) to worktree"
            )
        return str(path)
