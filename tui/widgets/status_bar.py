"""
Status Bar — top header showing model indicator and task status.

Shows the current model with its brand color, the current task,
and the run status.
"""
from __future__ import annotations

from textual.widgets import Static
from textual.containers import Horizontal

from tui.colors import get_model_color, format_model_display


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

    def compose(self):
        yield self._model
        yield self._status

    def update_state(self, state: dict) -> None:
        """Update model indicator and task status."""
        run = state.get("run") or {}
        status = run.get("status", "idle")
        current_node = run.get("current_node_id", "-")
        task_idx = run.get("current_task_index", 0)
        tasks = run.get("tasks", [])
        current_job_id = state.get("current_job_id")

        # Determine which model is active from recent jobs
        model_name = "idle"
        recent_jobs = state.get("recent_jobs", [])
        if current_job_id:
            for job in recent_jobs:
                if job.get("id") == current_job_id:
                    model_name = "running"
                    break

        # Try to extract model from router log
        # (The actual model name comes from logs/prompts/ files)
        # For now, show a generic indicator based on status
        if status == "running":
            model_display = "🔄 Running"
            color = "yellow"
        elif status == "paused":
            model_display = "⏸ Paused (HITL)"
            color = "yellow"
        elif status == "done":
            model_display = "✅ Complete"
            color = "green"
        elif status == "error":
            model_display = "❌ Error"
            color = "red"
        else:
            model_display = "● Kairos Ready"
            color = "cyan"

        self._model.update(f"[{color}]{model_display}[/{color}]")

        # Task status
        task_count = len(tasks)
        if task_count > 0:
            task_text = f"Task {task_idx + 1}/{task_count} · Node: {current_node}"
        else:
            task_text = "No active run"

        if run.get("last_error"):
            task_text += f" · Error: {run['last_error'][:50]}"

        self._status.update(task_text)
