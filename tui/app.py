"""
Kairos TUI — Main Application

A premium terminal UI for the Kairos agentic OS operator.

Replaces Streamlit with a Textual-based TUI that provides:
  - Three-panel layout (Agent Flow | Code Changes | Conversation Log)
  - Model-colored status indicators with brand colors
  - Real-time state polling from FastAPI backend
  - Inline HITL approvals
  - Syntax-highlighted code diffs
  - /btw — non-blocking side questions (modal dialog)
  - /blueprint — idea refinement wizard (multi-turn Q&A)
  - Command system (slash commands)
  - Keyboard shortcuts

Usage:
    cd ~/Projects/myforge
    source .venv/bin/activate
    python -m tui.app
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
from tui.widgets.btw_dialog import BTWDialog
from tui.widgets.blueprint import BlueprintScreen


class KairosApp(App):
    """Kairos Terminal User Interface."""

    TITLE = "🏔️ Kairos"
    CSS_PATH = "styles/kairos.tcss"

    BINDINGS = [
        Binding("ctrl+a", "approve", "Approve", priority=True),
        Binding("ctrl+r", "reject", "Reject", priority=True),
        Binding("ctrl+t", "btw", "BTW", priority=True),
        Binding("ctrl+b", "blueprint", "Blueprint", priority=True),
        Binding("ctrl+l", "toggle_log", "Toggle Log", priority=True),
        Binding("ctrl+n", "new_run", "New Run", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+h", "help", "Help", priority=True),
        Binding("tab", "focus_next", "Next Panel", show=False, priority=True),
        Binding("shift+tab", "focus_previous", "Prev Panel", show=False, priority=True),
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
        self._poll_count = 0

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

                # Get logs (every 3 polls = every 6 seconds)
                if self._poll_count % 3 == 0:
                    orch_log = self.api.get_logs(tail=50)
                    router_log = self.api.get_router_log(tail=20)
                    self.orch_log = orch_log
                    self.router_log = router_log
                    self._update_logs(orch_log, router_log)
                    # Update status bar with router log for model detection
                    self._update_status_bar(state, router_log)

                self._poll_count += 1
            except Exception:
                pass

            await asyncio.sleep(2)

    def _update_panels(self, state: dict) -> None:
        """Update all panels with new state."""
        try:
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

    def _update_status_bar(self, state: dict, router_log: str) -> None:
        """Update status bar with state + router log for model detection."""
        try:
            self.query_one(StatusBar).update_state(state, router_log)
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
            self.notify(f"Reset: {result}", timeout=3)
        elif cmd == "/step":
            result = self.api.step()
            self.notify(f"Step: {result.get('status', 'error')}", timeout=3)
        elif cmd == "/logs":
            self.show_log = not self.show_log
            conv = self.query_one(ConversationPanel)
            conv.display = self.show_log
        elif cmd == "/models":
            self._show_models()
        elif cmd == "/tools":
            self._show_tools()
        elif cmd == "/btw":
            self.action_btw()
        elif cmd == "/blueprint":
            self.action_blueprint()
        else:
            self.notify(f"Unknown command: {cmd}. Type /help for commands.", timeout=3)

    async def _start_run(self, goal: str) -> None:
        """Start a new run with the given goal."""
        self.notify(f"Starting run: {goal[:60]}...", timeout=3)
        result = self.api.start_run(goal)
        if "error" in result:
            self.notify(f"❌ Failed: {result['error']}", timeout=5)
        else:
            self.notify(f"✅ Job queued: {result.get('job_id', '?')}", timeout=3)

    # ---------- Actions (keyboard shortcuts) ----------

    def action_approve(self) -> None:
        """Ctrl+A — approve current HITL gate."""
        state = self.current_state
        run = state.get("run") or {}
        if run.get("status") != "paused":
            self.notify("No HITL gate pending.", timeout=2)
            return

        hitl_files = (state.get("files") or {}).get("hitl", {})
        if not hitl_files:
            self.notify("No HITL gate found.", timeout=2)
            return

        gate_name = list(hitl_files.keys())[0].replace(".json", "")
        self.api.approve(gate_name, "approved")
        self.notify(f"✅ Approved gate: {gate_name}", timeout=3)

    def action_reject(self) -> None:
        """Ctrl+R — reject current HITL gate."""
        state = self.current_state
        run = state.get("run") or {}
        if run.get("status") != "paused":
            self.notify("No HITL gate pending.", timeout=2)
            return

        hitl_files = (state.get("files") or {}).get("hitl", {})
        if not hitl_files:
            self.notify("No HITL gate found.", timeout=2)
            return

        gate_name = list(hitl_files.keys())[0].replace(".json", "")
        self.api.approve(gate_name, "rejected")
        self.notify(f"❌ Rejected gate: {gate_name}", timeout=3)

    def action_btw(self) -> None:
        """Ctrl+T — open /btw side question dialog."""
        # Determine which agent is currently running
        state = self.current_state
        run = state.get("run") or {}
        node = run.get("current_node_id", "agent")
        agent_name = node if node not in ("hitl_plan", "review_check", "done") else "agent"

        def on_btw_result(result):
            if result:
                # Send the BTW note to the backend
                self._send_btw(result)

        self.push_screen(BTWDialog(agent_name=agent_name), on_btw_result)

    def _send_btw(self, message: str) -> None:
        """Send a BTW note to the FastAPI backend."""
        try:
            import httpx
            r = httpx.post(
                f"{self.api.base_url}/btw",
                json={"message": message},
                timeout=5.0,
            )
            if r.status_code == 200:
                self.notify(f"💡 BTW note queued for next turn", timeout=3)
            else:
                self.notify(f"⚠️ BTW failed: {r.text}", timeout=5)
        except Exception as e:
            # If /btw endpoint doesn't exist yet, write to file directly
            try:
                from pathlib import Path
                import json
                btw_path = Path("state/btw_queue.json")
                btw_path.parent.mkdir(parents=True, exist_ok=True)
                queue = []
                if btw_path.exists():
                    queue = json.loads(btw_path.read_text())
                queue.append({"message": message, "timestamp": asyncio.time()})
                btw_path.write_text(json.dumps(queue, indent=2))
                self.notify(f"💡 BTW note saved to queue", timeout=3)
            except Exception as e2:
                self.notify(f"⚠️ BTW failed: {e2}", timeout=5)

    def action_blueprint(self) -> None:
        """Ctrl+B — open blueprint mode (idea refinement wizard)."""
        def on_blueprint_result(result):
            if result:
                # Start a run with the refined blueprint
                self.notify(f"📐 Starting run with blueprint...", timeout=3)
                self.api.start_run(result)

        self.push_screen(BlueprintScreen(api_url=self.api.base_url), on_blueprint_result)

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

    def _show_help(self) -> None:
        """Show help screen."""
        help_text = """[bold]🏔️ Kairos TUI — Keyboard Shortcuts[/bold]

[bold]Keys:[/bold]
  Tab          Switch between panels
  Ctrl+A       Approve HITL gate
  Ctrl+R       Reject HITL gate
  Ctrl+T       💡 /btw — side question (non-blocking)
  Ctrl+B       📐 /blueprint — idea refinement
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
  /btw         Side question (Ctrl+T)
  /blueprint   Idea refinement (Ctrl+B)

[bold]Usage:[/bold]
  Type a goal and press Enter to start a run.
  Example: "Add a /healthz endpoint to api/main.py"

[bold]BTW (Side Questions):[/bold]
  Press Ctrl+T while an agent is running to inject a note
  into the next turn WITHOUT interrupting the current generation.

[bold]Blueprint Mode:[/bold]
  Press Ctrl+B to refine a vague idea through Q&A with the LLM.
  The agent asks clarifying questions, then produces a detailed goal.
"""
        self.notify(help_text, timeout=15)

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
        """Show available models with their colors."""
        from tui.colors import MODEL_COLORS, format_model_display
        lines = ["[bold]Available Models:[/bold]", ""]
        for model_key, color in MODEL_COLORS.items():
            if model_key == "mock" or "llama" in model_key:
                continue
            display = format_model_display(model_key)
            lines.append(f"  ● [{color}]{display}[/{color}]")
        lines.append(f"  ● [dim]Groq Llama 3.3 (fallback)[/dim]")
        lines.append(f"  ● [dim]Mock (last resort)[/dim]")
        self.notify("\n".join(lines), timeout=8)

    def _show_tools(self) -> None:
        """Show registered tools."""
        tools = [
            "[bold]Filesystem (5):[/bold] read_file, write_file, edit_file, list_dir, mkdir",
            "[bold]Terminal (2):[/bold] execute, background_job",
            "[bold]Git (5):[/bold] git_status, git_diff, git_log, git_commit, git_branch",
            "[bold]Search (2):[/bold] grep, glob",
        ]
        self.notify("\n".join(tools), timeout=8)

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
