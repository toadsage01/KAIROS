"""
Blueprint Mode — idea refinement wizard.

A multi-turn conversation that helps the user refine a vague idea into
a concrete, actionable goal. Uses the same LiteLLM router to talk to
SOTA models.

Flow:
1. User describes a vague idea
2. Blueprint agent asks 3-5 clarifying questions (one at a time)
3. User answers each question
4. After all questions, agent produces a refined "blueprint prompt"
5. User can edit or approve the blueprint
6. Approved blueprint becomes the goal for the thinker agent
"""
from __future__ import annotations

from textual.screen import ModalScreen
from textual.widgets import Static, Input, Button, RichLog
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from rich.text import Text
from rich.panel import Panel

import httpx
import os


# The blueprint system prompt — teaches the model to ask clarifying questions
BLUEPRINT_SYSTEM_PROMPT = """You are a Blueprint Refinement Agent for Kairos.

Your job: help the user refine their vague idea into a concrete, actionable
goal that can be executed by an autonomous coding agent.

## Process
1. The user describes a vague idea
2. You ask ONE clarifying question at a time (max 5 questions total)
3. After each answer, acknowledge it and ask the next question
4. After all questions (or when you have enough info), produce a
   "BLUEPRINT" — a refined, detailed goal prompt

## Question Guidelines
- Ask about: scope, features, tech stack, design preferences, constraints
- One question at a time — NEVER ask multiple questions in one message
- Keep questions specific and actionable
- If the user's idea is already clear, skip questions and go to blueprint

## Output Format
When asking a question:
  QUESTION: <your question here>

When producing the blueprint (after all questions):
  BLUEPRINT: <the refined, detailed goal prompt that the thinker agent
  will use to decompose into tasks>

The blueprint should be:
- Specific (exact features, file names, technologies)
- Scoped (not too large — 1-3 tasks worth)
- Actionable (the coder can implement it without asking more questions)
"""


class BlueprintScreen(ModalScreen):
    """Full-screen modal for blueprint mode.

    Replaces the main TUI while active. Shows a conversation
    between the user and the blueprint agent.
    """

    DEFAULT_CSS = """
    BlueprintScreen {
        align: center middle;
    }
    BlueprintScreen > Vertical {
        width: 90%;
        height: 85%;
        background: $surface;
        border: solid $accent;
        padding: 1 2;
    }
    BlueprintScreen > Vertical > #blueprint-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    BlueprintScreen > Vertical > #blueprint-log {
        height: 1fr;
        border: solid $surface;
        margin-bottom: 1;
        padding: 1;
    }
    BlueprintScreen > Vertical > #blueprint-input {
        margin-bottom: 1;
    }
    BlueprintScreen > Vertical > Horizontal {
        align-horizontal: center;
        height: auto;
    }
    BlueprintScreen > Vertical > Horizontal > Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "submit_blueprint", "Submit Blueprint"),
    ]

    def __init__(self, api_url: str = "http://localhost:8000"):
        super().__init__()
        self.api_url = api_url
        self.conversation: list[dict] = []
        self.blueprint_text: str | None = None
        self.question_count = 0
        self.max_questions = 5
        self.waiting_for_blueprint = False

    def compose(self):
        yield Vertical(
            Static("📐 Blueprint Mode — Idea Refinement", id="blueprint-title"),
            RichLog(id="blueprint-log", highlight=False, markup=True),
            Input(
                placeholder="Describe your idea, or answer the question above...",
                id="blueprint-input",
            ),
            Horizontal(
                Button("Submit Blueprint (Ctrl+S)", id="submit-btn", variant="primary"),
                Button("Cancel (Esc)", id="cancel-btn"),
            ),
        )

    def on_mount(self):
        """Initialize the conversation."""
        self._log("Welcome to Blueprint Mode!")
        self._log("Describe your idea and I'll help refine it into an actionable goal.")
        self._log("")
        self.query_one("#blueprint-input", Input).focus()

    def _log(self, message: str):
        """Write to the blueprint log."""
        log = self.query_one("#blueprint-log", RichLog)
        log.write(message)

    def on_input_submitted(self, event: Input.Submitted):
        """Handle user input."""
        text = event.value.strip()
        if not text:
            return

        event.value = ""

        # Check if user is approving the blueprint
        if self.blueprint_text and text.lower() in ("yes", "y", "approve", "ok"):
            self.dismiss(self.blueprint_text)
            return

        # Check if user wants to edit the blueprint
        if self.blueprint_text and text.lower() in ("edit", "e"):
            self._log("[yellow]Edit the blueprint text and press Ctrl+S to submit[/yellow]")
            return

        # Add user message to conversation
        self.conversation.append({"role": "user", "content": text})
        self._log(f"[bold cyan]You:[/bold cyan] {text}")

        # Call the blueprint agent
        self._call_blueprint_agent()

    def _call_blueprint_agent(self):
        """Call the LLM to get the next question or blueprint."""
        self._log("[dim]🤔 Thinking...[/dim]")

        # Build messages for the LLM
        messages = [{"role": "system", "content": BLUEPRINT_SYSTEM_PROMPT}]
        messages.extend(self.conversation)

        try:
            # Call the same FastAPI backend's /run endpoint
            # But we need a direct LLM call, not a full agent run
            # Use LiteLLM directly via the router
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            from llm.router import route, load_agents

            # Use Claude for blueprint (best at conversation)
            prompt = self.conversation[-1]["content"]
            out = route(
                agent_name="thinker",  # reuse thinker's model config
                prompt=prompt,
                agents=load_agents(),
                extra_context=BLUEPRINT_SYSTEM_PROMPT,
                conversation_id=f"blueprint-{id(self)}",
            )

            self.conversation.append({"role": "assistant", "content": out})

            # Parse the response
            if out.startswith("QUESTION:"):
                question = out[len("QUESTION:"):].strip()
                self.question_count += 1
                self._log(f"[bold green]Blueprint Agent:[/bold green] {question}")
                self._log(f"[dim](Question {self.question_count}/{self.max_questions})[/dim]")

                if self.question_count >= self.max_questions:
                    self._log("[yellow]Max questions reached. Type 'finish' to get the blueprint.[/yellow]")

            elif out.startswith("BLUEPRINT:"):
                blueprint = out[len("BLUEPRINT:"):].strip()
                self.blueprint_text = blueprint
                self._log("")
                self._log("[bold green]═══ BLUEPRINT ═══[/bold green]")
                self._log(f"[bold]{blueprint}[/bold]")
                self._log("")
                self._log("[yellow]Approve this blueprint? Type 'yes' to start, 'edit' to modify, or Esc to cancel.[/yellow]")

            else:
                # General response
                self._log(f"[bold green]Blueprint Agent:[/bold green] {out}")

        except Exception as e:
            self._log(f"[red]Error: {e}[/red]")
            self._log("[yellow]You can type your goal directly and press Esc to use it as-is.[/yellow]")

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button clicks."""
        if event.button.id == "submit-btn":
            self.action_submit_blueprint()
        elif event.button.id == "cancel-btn":
            self.action_cancel()

    def action_submit_blueprint(self):
        """Submit the current blueprint (or conversation as goal)."""
        if self.blueprint_text:
            self.dismiss(self.blueprint_text)
        elif self.conversation:
            # Use the last user message as the goal
            last_user = [m for m in self.conversation if m["role"] == "user"]
            if last_user:
                self.dismiss(last_user[-1]["content"])
        else:
            self.dismiss(None)

    def action_cancel(self):
        """Cancel blueprint mode."""
        self.dismiss(None)
