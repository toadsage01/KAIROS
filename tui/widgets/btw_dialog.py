"""
BTW Dialog — non-blocking side question modal.

When the user presses Ctrl+T while an agent is running, this dialog
appears. The user types a note/question. The note is:
1. Sent to the FastAPI backend via POST /btw
2. Queued in state/btw_queue.json
3. The orchestrator checks the queue before the next agent call
4. The note is prepended to the agent's next prompt

This does NOT interrupt the current generation — it queues for the
NEXT turn.
"""
from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static, Input, Button
from textual.screen import ModalScreen
from textual.binding import Binding


class BTWDialog(ModalScreen):
    """Modal dialog for /btw side questions.

    Appears as an overlay. User types a note, presses Enter to send,
    or Escape to cancel.
    """

    DEFAULT_CSS = """
    BTWDialog {
        align: center middle;
    }
    BTWDialog > Vertical {
        width: 70%;
        height: auto;
        max-height: 50%;
        background: $surface;
        border: solid $accent;
        padding: 1 2;
    }
    BTWDialog > Vertical > #btw-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    BTWDialog > Vertical > #btw-hint {
        color: $text-disabled;
        margin-bottom: 1;
    }
    BTWDialog > Vertical > #btw-input {
        margin-bottom: 1;
    }
    BTWDialog > Vertical > Horizontal {
        align-horizontal: right;
        height: auto;
    }
    BTWDialog > Vertical > Horizontal > Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, agent_name: str = "agent"):
        super().__init__()
        self.agent_name = agent_name

    def compose(self):
        yield Vertical(
            Static("💡 BTW — Side Question", id="btw-title"),
            Static(
                f"The {self.agent_name} is working. Type a note or question "
                f"that will be injected into the next turn WITHOUT interrupting "
                f"the current generation.",
                id="btw-hint",
            ),
            Input(
                placeholder="e.g. Should the gallery use a masonry layout instead of grid?",
                id="btw-input",
            ),
            Static("", id="btw-status"),
        )

    def on_mount(self):
        self.query_one("#btw-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted):
        """Handle Enter key on the input."""
        if event.value.strip():
            self._send_btw(event.value.strip())
        else:
            self.dismiss(None)

    def _send_btw(self, message: str) -> None:
        """Send the BTW note to the backend."""
        self.query_one("#btw-status", Static).update(
            f"[green]✅ Note queued: \"{message[:50]}...\"[/green]"
        )
        # The actual API call is made by the parent app
        self.dismiss(message)

    def action_cancel(self):
        """Escape key — cancel without sending."""
        self.dismiss(None)
