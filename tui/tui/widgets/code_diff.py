"""
Code Diff Panel — right panel showing file changes with syntax highlighting.

Uses rich.syntax.Syntax for syntax-highlighted code blocks.
Parses the coder's output (fenced blocks with path= headers) and
renders each file with its appropriate language.
"""
from __future__ import annotations

import re
from typing import Any

from textual.widgets import Static, RichLog
from textual.containers import VerticalScroll
from rich.syntax import Syntax
from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown


# Parse fenced code blocks from coder output
_FENCE_RE = re.compile(
    r"```(\w+)(?:\s+path=(\S+))?(?:\s+action=(\w+))?\s*\n(.*?)```",
    re.DOTALL,
)


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

        # Current changes (coder output)
        if changes:
            for name, content in changes.items():
                self._render_coder_output(name, content)
        else:
            self._content.write("[dim]── No changes yet ──[/dim]")
            self._content.write("[dim]Coder output will appear here when available.[/dim]")

        # Current review
        if review:
            self._content.write("")
            self._content.write("[bold]── Latest Review ──[/bold]")
            for name, content in review.items():
                self._render_review(name, content)

        # Goal
        goal = root_files.get("goal.md")
        if goal:
            self._content.write("")
            self._content.write("[bold]── Goal ──[/bold]")
            # Truncate goal for display
            goal_lines = goal.split("\n")
            for line in goal_lines[:5]:
                self._content.write(line)

    def _render_coder_output(self, name: str, content: str) -> None:
        """Render coder output with syntax highlighting.

        Parses fenced code blocks and renders each with rich.syntax.
        """
        self._content.write(f"[bold cyan]📄 {name}[/bold cyan]")
        self._content.write("")

        # Try to parse fenced blocks
        blocks = list(_FENCE_RE.finditer(content))

        if blocks:
            for match in blocks:
                lang = match.group(1) or "text"
                path = match.group(2) or "(unknown)"
                action = match.group(3) or "modify"
                code = match.group(4).strip()

                # Action indicator
                action_icon = {"create": "✨", "modify": "📝", "delete": "🗑️"}.get(
                    action, "📝"
                )
                self._content.write(
                    f"[bold]{action_icon} {path}[/bold] [dim]({lang}, {action})[/dim]"
                )

                # Syntax-highlighted code
                try:
                    syntax = Syntax(
                        code,
                        lang,
                        theme="monokai",
                        line_numbers=True,
                        word_wrap=True,
                        background_color="default",
                    )
                    self._content.write(syntax)
                except Exception:
                    # Fallback to plain text
                    self._content.write(code)

                self._content.write("")
        else:
            # No fenced blocks found — show raw content (truncated)
            display = content[:3000]
            if len(content) > 3000:
                display += f"\n... ({len(content)} chars total, truncated)"
            self._content.write(display)

    def _render_review(self, name: str, content: str) -> None:
        """Render review output with status highlighting."""
        # Check for status header
        status_match = re.search(r"<!-- status: (\w+) -->", content)
        status = status_match.group(1) if status_match else "unknown"

        status_display = {
            "approved": "[green]✅ APPROVED[/green]",
            "rejected": "[red]❌ REJECTED[/red]",
            "unverifiable": "[yellow]⚠ UNVERIFIABLE[/yellow]",
        }.get(status, f"[dim]Status: {status}[/dim]")

        self._content.write(f"[bold]🔍 {name}[/bold] — {status_display}")
        self._content.write("")

        # Show review content (truncated)
        # Strip the status header for display
        display_content = re.sub(r"<!-- status: \w+ -->\n?", "", content)
        display = display_content[:1500]
        if len(display_content) > 1500:
            display += "\n... (truncated)"
        self._content.write(display)
