"""
Kairos TUI — Main Application

A premium terminal UI for the Kairos agentic OS operator.

Replaces Streamlit with a Textual-based TUI that provides:
  - Three-panel layout (Agent Flow | Code Changes | Conversation Log)
  - Model-colored status indicators
  - Real-time state polling from FastAPI backend
  - Inline HITL approvals
  - Command system (slash commands)
  - Keyboard shortcuts

Usage:
    cd ~/Projects/myforge
    source .venv/bin/activate
    python -m tui.app

    # Or with custom API URL:
    MYFORGE_API_URL=http://localhost:8000 python -m tui.app
"""
from __future__ import annotations

import asyncio
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input, Static
from textual.binding import Binding
from textual.reactive import reactive

from tui.api_client import ApiClient
from tui.widgets.agent_flow import AgentFlowPanel
from tui.widgets.code_diff import CodeDiffPanel
from tui.widgets.conversation import ConversationPanel
from tui.widgets.status_bar import StatusBar


class KairosApp(App):
    """Kairos Terminal User Interface."""

    TITLE = "🏔️ Kairos"
    CSS_PATH = "styles/kairos.tcss"

    BINDINGS = [
        Binding("ctrl+a", "approve", "Approve"),
        Binding("ctrl+r", "reject", "Reject"),
        Binding("ctrl+l", "toggle_log", "Toggle Log"),
        Binding("ctrl+n", "new_run", "New Run"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+h", "help", "Help"),
        Binding("tab", "focus_next", "Next Panel", show=False),
        Binding("shift+tab", "focus_previous", "Prev Panel", show=False),
    ]

    # Reactive state
    current_state: reactive[dict] = reactive(dict, layout=False)
    orch_log: reactive[str] = reactive("", layout=False)
    router_log: reactive[str] = reactive("", layout=False)
    show_log: reactive[bool] = reactive(True)

    def __init__(self):
        super().__init__()
        self.api = ApiClient()
        self._poll_active = False

    def compose(self) -> ComposeResult:
        """Create the layout."""
        yield StatusBar()
        yield Horizontal(
            AgentFlowPanel(),
            CodeDiffPanel(),
            id="main-content",
        )
        yield ConversationPanel()
        yield Input(
            placeholder="Type a goal and press Enter, or use /help for commands",
            id="command-input",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Start polling when app mounts."""
        self._poll_active = True
        self._poll_state()

    @work(exclusive=True)
    async def _poll_state(self) -> None:
        """Poll FastAPI /state every 2 seconds.

        This is the TUI's heartbeat — it fetches the latest state
        and updates all panels.
        """
        while self._poll_active:
            try:
                # Get state
                state = self.api.get_state()
                if "error" not in state:
                    self.current_state = state
                    self._update_panels(state)

                # Get logs (less frequently — every 3 polls)
                if self._poll_count % 3 == 0:
                    orch_log = self.api.get_logs(tail=50)
                    router_log = self.api.get_router_log(tail=20)
                    self.orch_log = orch_log
                    self.router_log = router_log
                    self._update_logs(orch_log, router_log)

                self._poll_count += 1
            except Exception:
                pass

            await asyncio.sleep(2)

    _poll_count = 0

    def _update_panels(self, state: dict) -> None:
        """Update all panels with new state."""
        try:
            self.query_one(StatusBar).update_state(state)
            self.query_one(AgentFlowPanel).update_state(state)
            self.query_one(CodeDiffPanel).update_state(state)
        except Exception:
            pass  # Widgets might not be mounted yet

    def _update_logs(self, orch_log: str, router_log: str) -> None:
        """Update conversation panel with new logs."""
        try:
            self.query_one(ConversationPanel).update_logs(orch_log, router_log)
        except Exception:
            pass

    # ---------- Input handling ----------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input from the command bar."""
        text = event.value.strip()
        if not text:
            return

        # Clear input
        event.input.value = ""

        # Check if it's a slash command
        if text.startswith("/"):
            await self._handle_command(text)
        else:
            # It's a goal — start a run
            await self._start_run(text)

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/help":
            self._show_help()
        elif cmd == "/status":
            state = self.api.get_state()
            self._show_status(state)
        elif cmd == "/reset":
            result = self.api.reset()
            self._notify(f"Reset: {result}")
        elif cmd == "/step":
            result = self.api.step()
            self._notify(f"Step: {result.get('status', 'error')}")
        elif cmd == "/logs":
            self.show_log = not self.show_log
            conv = self.query_one(ConversationPanel)
            conv.display = self.show_log
        elif cmd == "/models":
            self._show_models()
        elif cmd == "/tools":
            self._show_tools()
        elif cmd == "/btw":
            self._notify("⚠️ /btw not yet implemented — coming in Batch 2")
        elif cmd == "/blueprint":
            self._notify("⚠️ /blueprint not yet implemented — coming in Batch 2")
        else:
            self._notify(f"Unknown command: {cmd}. Type /help for available commands.")

    async def _start_run(self, goal: str) -> None:
        """Start a new run with the given goal."""
        self._notify(f"Starting run: {goal[:60]}...")
        result = self.api.start_run(goal)
        if "error" in result:
            self._notify(f"❌ Failed: {result['error']}")
        else:
            self._notify(f"✅ Job queued: {result.get('job_id', '?')}")

    # ---------- Actions (keyboard shortcuts) ----------

    def action_approve(self) -> None:
        """Ctrl+A — approve current HITL gate."""
        state = self.current_state
        run = state.get("run") or {}
        if run.get("status") != "paused":
            self._notify("No HITL gate pending.")
            return

        hitl_files = (state.get("files") or {}).get("hitl", {})
        if not hitl_files:
            self._notify("No HITL gate found.")
            return

        gate_name = list(hitl_files.keys())[0].replace(".json", "")
        result = self.api.approve(gate_name, "approved")
        self._notify(f"✅ Approved gate: {gate_name}")

    def action_reject(self) -> None:
        """Ctrl+R — reject current HITL gate."""
        state = self.current_state
        run = state.get("run") or {}
        if run.get("status") != "paused":
            self._notify("No HITL gate pending.")
            return

        hitl_files = (state.get("files") or {}).get("hitl", {})
        if not hitl_files:
            self._notify("No HITL gate found.")
            return

        gate_name = list(hitl_files.keys())[0].replace(".json", "")
        result = self.api.approve(gate_name, "rejected")
        self._notify(f"❌ Rejected gate: {gate_name}")

    def action_toggle_log(self) -> None:
        """Ctrl+L — toggle conversation log panel."""
        self.show_log = not self.show_log
        try:
            conv = self.query_one(ConversationPanel)
            conv.display = self.show_log
        except Exception:
            pass

    def action_new_run(self) -> None:
        """Ctrl+N — focus the input bar for a new run."""
        try:
            input_bar = self.query_one("#command-input", Input)
            input_bar.focus()
            input_bar.value = ""
        except Exception:
            pass

    def action_help(self) -> None:
        """Ctrl+H — show help."""
        self._show_help()

    # ---------- Display helpers ----------

    def _notify(self, message: str) -> None:
        """Show a temporary notification."""
        self.app.log(message) if hasattr(self.app, 'log') else None
        # Use the built-in notification system
        try:
            self.notify(message, timeout=3)
        except Exception:
            pass

    def _show_help(self) -> None:
        """Show help screen."""
        help_text = """[bold]Kairos TUI — Keyboard Shortcuts[/bold]

[bold]Keys:[/bold]
  Tab          Switch between panels
  Ctrl+A       Approve HITL gate
  Ctrl+R       Reject HITL gate
  Ctrl+L       Toggle conversation log
  Ctrl+N       Focus input for new run
  Ctrl+Q       Quit Kairos

[bold]Commands:[/bold]
  /help        Show this help
  /status      Show current run status
  /reset       Reset all state
  /step        Advance one DAG step
  /logs        Toggle log panel
  /models      List available models
  /tools       List registered tools
  /btw         Side question (coming soon)
  /blueprint   Idea refinement (coming soon)

[bold]Usage:[/bold]
  Type a goal and press Enter to start a run.
  Example: "Add a /healthz endpoint to api/main.py"
"""
        self.notify(help_text, timeout=10)

    def _show_status(self, state: dict) -> None:
        """Show status notification."""
        run = state.get("run") or {}
        status = run.get("status", "(no run)")
        node = run.get("current_node_id", "-")
        tasks = run.get("tasks", [])
        task_idx = run.get("current_task_index", 0)
        error = run.get("last_error", "")

        msg = f"Status: {status} | Node: {node} | Task: {task_idx + 1}/{len(tasks)}"
        if error:
            msg += f" | Error: {error[:80]}"

        self.notify(msg, timeout=5)

    def _show_models(self) -> None:
        """Show available models."""
        # This would normally query /v1/models from WebAI2API
        # For now, show the configured models
        self.notify(
            "Models: Claude Sonnet 5, GPT-4o, DeepSeek, Gemini Pro, GLM-5.2, Groq",
            timeout=5,
        )

    def _show_tools(self) -> None:
        """Show registered tools."""
        tools = [
            "Filesystem: read_file, write_file, edit_file, list_dir, mkdir",
            "Terminal: execute, background_job",
            "Git: git_status, git_diff, git_log, git_commit, git_branch",
            "Search: grep, glob",
        ]
        self.notify("\n".join(tools), timeout=5)

    def on_unmount(self) -> None:
        """Cleanup when app exits."""
        self._poll_active = False
        self.api.close()


def main():
    """Entry point for the TUI."""
    app = KairosApp()
    app.run()


if __name__ == "__main__":
    main()
