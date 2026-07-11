"""Reviewer — reads changes + worktree files, writes review/{task_id}.md.

Updated for Batch 2: extends ToolAgent so it can optionally use tools
(run_tests, git_diff, read_file) to verify the coder's output.

If use_tools=False (default), operates in single-pass mode (backward
compatible with existing behavior).
"""
from __future__ import annotations

import re
from typing import Any

from agents.base import AgentBlocked, AgentContext
from agents.tool_agent import ToolAgent
from core.parser import extract_blocked


class ReviewerAgent(ToolAgent):
    name = "reviewer"
    # Tools the reviewer can use (when use_tools=True)
    use_tools = False  # set True in agents.yaml to enable
    allowed_tools = [
        "read_file",      # read files the coder changed
        "list_dir",       # see what files exist
        "grep",           # search for patterns
        "execute",        # run pytest, ruff, etc.
        "git_diff",       # see what changed
        "git_status",     # see uncommitted changes
    ]

    def template_vars(self, ctx: AgentContext) -> dict[str, Any]:
        vars_ = super().template_vars(ctx)
        task = ctx.task or {}

        # Build the coder output display
        changes = self.state.read_md(ctx.task_id, subdir="changes") or ""
        vars_["coder_response_or_current_files"] = changes

        # If there were prior rejections, show them
        review = self.state.read_md(ctx.task_id, subdir="review") or ""
        if review and "<!-- status: rejected -->" in review:
            vars_["reviewer_rejection_list"] = review

        return vars_

    def build_prompt(self, ctx: AgentContext) -> str:
        """Build the user prompt for the reviewer.

        In tool mode, the reviewer gets a short prompt and uses tools to
        investigate. In single-pass mode, it gets the full coder output
        in the prompt.
        """
        task = ctx.task or {}
        parts = [
            f"Review the coder's output for task {ctx.task_id}.",
            f"\nTask title: {task.get('title', '')}",
            f"\nTask description: {task.get('description', '')}",
        ]

        # Show the coder's changes
        changes = self.state.read_md(ctx.task_id, subdir="changes") or ""
        if changes:
            parts.append(f"\n--- changes/{ctx.task_id}.md ---\n{changes}\n--- end ---")

        # Show the actual files in the worktree (if available)
        if ctx.worktree is not None:
            existing = ctx.worktree.list_files()
            if existing:
                parts.append("\n--- files in worktree ---")
                for f in existing[:20]:
                    try:
                        content = ctx.worktree.read_file(f) or ""
                        lang = f.rsplit(".", 1)[-1] if "." in f else "text"
                        parts.append(f"\n### {f}\n```{lang}\n{content[:3000]}\n```")
                    except Exception:
                        parts.append(f"\n### {f} (could not read)")
                parts.append("--- end ---")

        # Prior rejection info
        extra = ctx.extra or {}
        prior_count = extra.get("prior_rejection_count", 0)
        if prior_count > 0:
            parts.append(f"\nNote: This is review iteration {prior_count}. "
                        f"The coder has addressed previous defects.")

        return "\n".join(parts)

    def write_output(self, ctx: AgentContext, model_output: str) -> str:
        # Check for blocked
        blocked = extract_blocked(model_output)
        if blocked:
            raise AgentBlocked(blocked)

        # Parse STATUS: line
        m = re.search(r"STATUS:\s*(approved|rejected)",
                      model_output, re.IGNORECASE)
        status = m.group(1).lower() if m else "rejected"

        # Inject status header for the orchestrator's branch parser
        header = f"<!-- status: {status} -->\n"
        path = self.state.write_md(
            ctx.task_id, header + model_output, subdir="review"
        )
        return str(path)
