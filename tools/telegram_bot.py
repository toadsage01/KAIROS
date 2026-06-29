"""
Telegram Bot — mobile HITL notifications + remote approval.

When the orchestrator pauses at a HITL gate, this bot sends a Telegram
message with inline Approve/Reject buttons. The user can approve from
their phone; the bot calls myforge's /approve endpoint to resume the
orchestrator (which runs in the async background worker thread).

Architecture:
  - Bot runs in its own background thread (separate from the orchestrator worker)
  - Uses long-polling (no public URL needed, no webhook setup)
  - Callbacks come back as POST /approve to the local API
  - Token + chat_id from env vars; if missing, bot is a no-op

Future Kairos extensions:
  - Run completion notifications ("✅ Kairos finished your task")
  - Error notifications ("❌ Run failed at coder: rate limit hit")
  - Daily digests
  - Two-way chat (user asks "what's the status?" — bot replies)
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import httpx

# Optional import — python-telegram-bot is heavy
try:
    import telegram
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
    )
    _HAS_TG = True
except ImportError:
    telegram = None  # type: ignore
    _HAS_TG = False


class TelegramBot:
    """Single-instance Telegram bot. Polls for updates in a background thread.

    If python-telegram-bot isn't installed or token isn't set, all methods
    degrade to no-ops. The rest of myforge keeps working.
    """

    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api_base = api_base
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.available = _HAS_TG and bool(self.token) and bool(self.chat_id)
        self._app: Any | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---------- lifecycle ----------
    def start(self) -> None:
        """Start polling for updates in a background thread."""
        if not self.available:
            return
        if self._thread is not None and self._thread.is_alive():
            return

        def _run():
            try:
                # Build the application
                self._app = (
                    Application.builder()
                    .token(self.token)
                    .build()
                )
                # Register handlers
                self._app.add_handler(CommandHandler("start", self._cmd_start))
                self._app.add_handler(CommandHandler("status", self._cmd_status))
                self._app.add_handler(CallbackQueryHandler(self._callback))
                # Start polling (blocks in this thread)
                self._app.run_polling(
                    poll_interval=2.0,
                    stop_signals=self._stop,
                )
            except Exception as e:  # noqa: BLE001
                # Don't crash the whole app if Telegram fails
                print(f"[telegram] bot thread error: {e}", flush=True)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._app:
            try:
                self._app.stop_running()
            except Exception:
                pass

    # ---------- public API ----------
    def send_message(self, text: str, reply_markup: Any | None = None) -> bool:
        """Send a message to the configured chat. Returns True on success."""
        if not self.available:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                url = f"https://api.telegram.org/bot{self.token}/sendMessage"
                payload: dict[str, Any] = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                }
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                r = client.post(url, json=payload)
                return r.status_code == 200
        except Exception:
            return False

    def send_hitl_notification(
        self,
        gate: str,
        goal: str,
        plan_summary: str,
    ) -> bool:
        """Send a HITL gate notification with Approve/Reject buttons.

        Args:
            gate: The HITL gate name (e.g. "plan_approval")
            goal: The current run's goal
            plan_summary: A short summary of the plan (first 500 chars)
        """
        if not self.available:
            return False

        # Truncate for Telegram readability
        goal_short = goal[:200] if goal else "(no goal)"
        plan_short = plan_summary[:800] if plan_summary else "(no plan)"

        text = (
            f"⏸ *HITL Gate Paused*\n\n"
            f"*Gate:* `{gate}`\n\n"
            f"*Goal:*\n{goal_short}\n\n"
            f"*Plan:*\n```\n{plan_short}\n```\n\n"
            f"Tap a button to decide:"
        )

        # Inline keyboard with callback_data = "approve:{gate}" or "reject:{gate}"
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{gate}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{gate}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard) if _HAS_TG else None
        return self.send_message(text, reply_markup=reply_markup)

    def send_completion_notification(
        self,
        goal: str,
        tasks_count: int,
        status: str,
    ) -> bool:
        """Send a run-completion notification."""
        if not self.available:
            return False
        emoji = "✅" if status == "done" else "❌"
        text = (
            f"{emoji} *Run {status}*\n\n"
            f"*Goal:* {goal[:200]}\n"
            f"*Tasks:* {tasks_count}\n"
            f"*Status:* `{status}`"
        )
        return self.send_message(text)

    # ---------- handlers (run in bot's thread) ----------
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start — verify the bot is alive."""
        if update.effective_chat and str(update.effective_chat.id) != self.chat_id:
            # Not our chat — ignore (security: only respond to configured chat)
            return
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Kairos online. I'll notify you when HITL gates pause.",
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status — fetch current orchestrator state."""
        if update.effective_chat and str(update.effective_chat.id) != self.chat_id:
            return
        try:
            r = httpx.get(f"{self.api_base}/state", timeout=5.0)
            data = r.json()
            run = data.get("run") or {}
            status = run.get("status", "(no run)")
            node = run.get("current_node_id", "-")
            tasks = run.get("tasks", [])
            text = (
                f"*Status:* `{status}`\n"
                f"*Node:* `{node}`\n"
                f"*Tasks:* {len(tasks)}\n"
                f"*Current job:* `{data.get('current_job_id', '-')}`"
            )
        except Exception as e:
            text = f"Failed to fetch status: {e}"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

    async def _callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline button presses (approve/reject)."""
        query = update.callback_query
        if not query:
            return
        # Security: only respond to configured chat
        if query.message and str(query.message.chat.id) != self.chat_id:
            return

        data = query.data or ""
        if ":" not in data:
            await query.answer("Invalid callback")
            return

        action, gate = data.split(":", 1)
        if action not in ("approve", "reject"):
            await query.answer("Unknown action")
            return

        decision = "approved" if action == "approve" else "rejected"
        await query.answer(f"{decision} — resuming...")

        # Call myforge's /approve endpoint
        try:
            r = httpx.post(
                f"{self.api_base}/approve",
                json={"gate": gate, "decision": decision},
                timeout=10.0,
            )
            if r.status_code == 200:
                job = r.json()
                await context.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"🔄 Job `{job.get('job_id')}` queued. Orchestrator resuming.",
                )
            else:
                await context.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"❌ Approve failed: HTTP {r.status_code}",
                )
        except Exception as e:
            await context.bot.send_message(
                chat_id=self.chat_id,
                text=f"❌ Approve failed: {e}",
            )


# ---------- singleton ----------
_singleton: TelegramBot | None = None
_lock = threading.Lock()


def get_telegram_bot(api_base: str = "http://localhost:8000") -> TelegramBot:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = TelegramBot(api_base=api_base)
    return _singleton
