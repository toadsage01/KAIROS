"""
Code Diff Panel — right panel showing file changes.

Displays the coder's output (code blocks with path= headers) and
the actual files in the worktree.
"""
from __future__ import annotations

from textual.widgets import Static, RichLog
from textual.containers import VerticalScroll


class CodeDiffPanel(VerticalScroll):
    """Right panel showing code changes and file diffs."""

    DEFAULT_CSS = """
    CodeDiffPanel {
        width: 2fr;
        border: solid $surface;
        padding: 0;
    }
    CodeDiffPanel > .panel-title {
        background: $surface;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self):
        super().__init__()
        self._title = Static("  Code Changes", classes="panel-title")
        self._content = RichLog(highlight=False, markup=True)

    def compose(self):
        yield self._title
        yield self._content

    def update_state(self, state: dict) -> None:
        """Update with latest file changes from state."""
        files = state.get("files") or {}
        changes = files.get("changes", {})
        review = files.get("review", {})
        root_files = files.get("root", {})

        self._content.clear()

        lines = []

        # Current changes (coder output)
        if changes:
            lines.append("── Latest Coder Output ──")
            for name, content in changes.items():
                # Show file name + first few lines
                lines.append(f"\n[bold]📄 {name}[/bold]")
                # Truncate long content for display
                display = content[:2000]
                if len(content) > 2000:
                    display += f"\n... ({len(content)} chars total, truncated)"
                lines.append(display)
                lines.append("")
        else:
            lines.append("── No changes yet ──")
            lines.append("Coder output will appear here when available.")

        # Current review
        if review:
            lines.append("")
            lines.append("── Latest Review ──")
            for name, content in review.items():
                lines.append(f"\n[bold]🔍 {name}[/bold]")
                display = content[:1000]
                if len(content) > 1000:
                    display += f"\n... (truncated)"
                lines.append(display)

        # Goal and plan
        goal = root_files.get("goal.md")
        if goal:
            lines.append("")
            lines.append("── Goal ──")
            lines.append(goal[:500])

        for line in lines:
            self._content.write(line)
