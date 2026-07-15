"""
Conversation Panel — bottom panel showing streaming agent log.

Displays real-time orchestrator events, model fallback events,
and tool call results.
"""
from __future__ import annotations

from textual.widgets import Static, RichLog
from textual.containers import VerticalScroll


class ConversationPanel(VerticalScroll):
    """Bottom panel showing conversation log and router events."""

    DEFAULT_CSS = """
    ConversationPanel {
        dock: bottom;
        height: 40%;
        border: solid $surface;
        border-bottom: none;
        padding: 0;
    }
    ConversationPanel > .panel-title {
        background: $surface;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self):
        super().__init__()
        self._title = Static("  Conversation Log", classes="panel-title")
        self._content = RichLog(highlight=False, markup=True)
        self._last_log = ""
        self._last_router_log = ""

    def compose(self):
        yield self._title
        yield self._content

    def update_logs(self, orch_log: str, router_log: str) -> None:
        """Update with latest log content.

        Only re-renders if the logs changed (avoids flickering).
        """
        if orch_log == self._last_log and router_log == self._last_router_log:
            return

        self._last_log = orch_log
        self._last_router_log = router_log

        self._content.clear()

        lines = []

        # Router log (model events) — show first (most recent at bottom)
        if router_log:
            lines.append("── Router Events (model fallbacks) ──")
            router_lines = router_log.split("\n")
            # Show last 10 router events
            for line in router_lines[-10:]:
                if line.strip():
                    # Color-code based on content
                    if "OK (LIVE)" in line:
                        lines.append(f"[green]{line}[/green]")
                    elif "OK (MOCK)" in line:
                        lines.append(f"[dim]{line}[/dim]")
                    elif "failed" in line:
                        lines.append(f"[red]{line}[/red]")
                    elif "prompt_log" in line:
                        lines.append(f"[cyan]{line}[/cyan]")
                    else:
                        lines.append(line)
            lines.append("")

        # Orchestrator log (agent events)
        if orch_log:
            lines.append("── Orchestrator Log ──")
            orch_lines = orch_log.split("\n")
            # Show last 30 lines
            for line in orch_lines[-30:]:
                if line.strip():
                    # Highlight key events
                    if "ERROR" in line:
                        lines.append(f"[red]{line}[/red]")
                    elif "approved" in line:
                        lines.append(f"[green]{line}[/green]")
                    elif "paused" in line:
                        lines.append(f"[yellow]{line}[/yellow]")
                    elif "merged" in line:
                        lines.append(f"[green]{line}[/green]")
                    elif "wrote" in line:
                        lines.append(f"[cyan]{line}[/cyan]")
                    elif "job queued" in line:
                        lines.append(f"[dim]{line}[/dim]")
                    else:
                        lines.append(line)

        if not lines:
            lines.append("(waiting for events...)")

        for line in lines:
            self._content.write(line)
