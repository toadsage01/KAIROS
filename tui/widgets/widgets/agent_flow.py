"""
Agent Flow Panel — left panel showing agent execution progress.

Displays the DAG flow: thinker → HITL → coder → reviewer → branch → done
with status icons and timing.
"""
from __future__ import annotations

from textual.widgets import Static, RichLog
from textual.containers import VerticalScroll
from rich.text import Text
from rich.table import Table

from tui.colors import get_agent_icon, get_model_color


class AgentFlowPanel(VerticalScroll):
    """Left panel showing agent execution flow."""

    DEFAULT_CSS = """
    AgentFlowPanel {
        width: 1fr;
        border: solid $surface;
        padding: 0;
    }
    AgentFlowPanel > .panel-title {
        background: $surface;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self):
        super().__init__()
        self._title = Static("  Agent Flow", classes="panel-title")
        self._content = RichLog(highlight=False, markup=True)

    def compose(self):
        yield self._title
        yield self._content

    def update_state(self, state: dict) -> None:
        """Update the panel with latest state from API."""
        run = state.get("run") or {}
        status = run.get("status", "(no run)")
        current_node = run.get("current_node_id", "-")
        task_idx = run.get("current_task_index", 0)
        tasks = run.get("tasks", [])
        recent_jobs = state.get("recent_jobs", [])
        current_job_id = state.get("current_job_id")

        self._content.clear()

        # Build the agent flow display
        lines = []

        # Status line
        status_emoji = {
            "running": "🔄",
            "paused": "⏸",
            "done": "✅",
            "error": "❌",
        }.get(status, "❓")

        lines.append(f"{status_emoji} Status: {status}")
        lines.append(f"📍 Node: {current_node}")
        lines.append(f"📋 Task: {task_idx + 1}/{len(tasks)}")
        if current_job_id:
            lines.append(f"🔧 Job: {current_job_id}")
        lines.append("")

        # Task list
        if tasks:
            lines.append("── Tasks ──")
            for i, task in enumerate(tasks):
                icon = "👉" if i == task_idx else "  "
                task_id = task.get("id", "?")
                title = task.get("title", "?")[:40]
                lines.append(f"{icon} {task_id}: {title}")
            lines.append("")

        # Agent flow (simplified DAG visualization)
        lines.append("── DAG Flow ──")
        flow_steps = [
            ("thinker", "Thinker", "plans tasks"),
            ("hitl_plan", "HITL", "human approval"),
            ("coder", "Coder", "writes code"),
            ("reviewer", "Reviewer", "evaluates"),
            ("review_check", "Branch", "approve/reject"),
            ("bugfixer", "Bugfixer", "fixes defects"),
            ("done", "Done", "complete"),
        ]

        for node_id, name, desc in flow_steps:
            if node_id == current_node:
                icon = "●"
                color = "yellow"
            elif status == "done" and node_id == "done":
                icon = "✓"
                color = "green"
            elif status == "error" and node_id == current_node:
                icon = "✗"
                color = "red"
            else:
                icon = "○"
                color = "dim"

            lines.append(f"  [{color}]{icon} {name}[/{color}] — {desc}")

        lines.append("")

        # Recent jobs
        if recent_jobs:
            lines.append("── Recent Jobs ──")
            for job in recent_jobs[:5]:
                jid = job.get("id", "?")[:8]
                jkind = job.get("kind", "?")
                jstatus = job.get("status", "?")
                jemoji = {
                    "queued": "⏳",
                    "running": "🔄",
                    "done": "✅",
                    "error": "❌",
                    "cancelled": "🚫",
                }.get(jstatus, "❓")
                lines.append(f"  {jemoji} {jid} {jkind} — {jstatus}")

        # Tools available
        lines.append("")
        lines.append("── Tools (14) ──")
        lines.append("  📁 fs(5)  🔧 term(2)  🌿 git(5)  🔍 search(2)")

        # Write to log
        for line in lines:
            self._content.write(line)
