"""
Status Bar — top header showing model indicator and task status.

Shows the current model with its brand color, the current task,
and the run status. Parses router log to show which model is actually
running (not just generic "running" status).
"""
from __future__ import annotations

import re
from textual.widgets import Static
from textual.containers import Horizontal

from tui.colors import get_model_color, format_model_display


# Parse router log lines like:
# [2026-07-15T02:01:25] agent=thinker model=openai/claude-sonnet-5@localhost OK (LIVE)
# [2026-07-15T02:01:25] agent=thinker model=openai/claude-sonnet-5@localhost failed: ... -> trying fallback
_MODEL_RE = re.compile(
    r"agent=(\w+)\s+model=(\S+)\s+(OK|failed)"
)


class StatusBar(Horizontal):
    """Top header with model indicator and task status."""

    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 3;
        background: $surface;
        border-bottom: solid $primary;
        padding: 0 1;
    }
    StatusBar > #model-indicator {
        width: auto;
        padding: 0 2;
        content-align: center middle;
    }
    StatusBar > #task-status {
        width: 1fr;
        padding: 0 2;
        content-align: center middle;
    }
    """

    def __init__(self):
        super().__init__()
        self._model = Static("● Kairos", id="model-indicator")
        self._status = Static("Ready", id="task-status")
        self._current_model = ""
        self._current_agent = ""

    def compose(self):
        yield self._model
        yield self._status

    def update_state(self, state: dict, router_log: str = "") -> None:
        """Update model indicator and task status.

        Args:
            state: Full state from /state endpoint
            router_log: Latest router log (to extract active model)
        """
        run = state.get("run") or {}
        status = run.get("status", "idle")
        current_node = run.get("current_node_id", "-")
        task_idx = run.get("current_task_index", 0)
        tasks = run.get("tasks", [])
        current_job_id = state.get("current_job_id")

        # Parse router log to find the most recent model
        if router_log:
            active_model = self._extract_active_model(router_log, status, current_job_id)
            if active_model:
                self._current_model = active_model["model"]
                self._current_agent = active_model["agent"]

        # Build display
        if status == "running" and self._current_model:
            model_display = format_model_display(self._current_model)
            color = get_model_color(self._current_model)
            agent_label = self._current_agent.title() if self._current_agent else "Agent"
            self._model.update(
                f"● [{color}]{model_display}[/{color}]  [dim]{agent_label}[/dim]"
            )
        elif status == "paused":
            self._model.update("[yellow]⏸ Paused (HITL gate)[/yellow]")
        elif status == "done":
            self._model.update("[green]✅ Complete[/green]")
        elif status == "error":
            self._model.update("[red]❌ Error[/red]")
        else:
            self._model.update("[cyan]● Kairos Ready[/cyan]")

        # Task status
        task_count = len(tasks)
        if task_count > 0:
            task_text = f"Task {task_idx + 1}/{task_count} · Node: {current_node}"
        else:
            task_text = "No active run"

        if run.get("last_error"):
            task_text += f" · [red]Error: {run['last_error'][:60]}[/red]"

        self._status.update(task_text)

    def _extract_active_model(
        self, router_log: str, status: str, current_job_id: str | None
    ) -> dict | None:
        """Extract the most recently active model from router log.

        Looks for the last 'OK (LIVE)' or 'OK (MOCK)' entry.
        Returns {"model": "openai/claude-sonnet-5@localhost", "agent": "thinker"}
        or None if no active model found.
        """
        if status != "running":
            return None

        lines = router_log.strip().split("\n")
        # Search from the end for the most recent OK
        for line in reversed(lines):
            if "OK (LIVE)" in line or "OK (MOCK)" in line:
                m = _MODEL_RE.search(line)
                if m:
                    return {
                        "agent": m.group(1),
                        "model": m.group(2),
                        "status": m.group(3),
                    }
        return None
