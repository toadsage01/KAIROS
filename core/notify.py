"""
Notification dispatcher — abstraction over notification channels.

Currently supports Telegram. Future: SMS, email, push, etc.

The orchestrator calls notify_hitl_paused() when a gate pauses. The
dispatcher fans out to all configured channels. If no channels are
configured, calls are no-ops (myforge works exactly as before).
"""
from __future__ import annotations

from tools.telegram_bot import get_telegram_bot


def notify_hitl_paused(
    gate: str,
    goal: str,
    plan_summary: str,
) -> None:
    """Fire HITL notifications on all configured channels.

    Called by the orchestrator when a HITL gate pauses. Each channel
    handles its own failures silently — notifications are best-effort.
    """
    # Telegram
    try:
        bot = get_telegram_bot()
        if bot.available:
            bot.send_hitl_notification(gate, goal, plan_summary)
    except Exception:
        pass  # notifications are best-effort


def notify_run_complete(
    goal: str,
    tasks_count: int,
    status: str,
) -> None:
    """Fire run-completion notifications on all configured channels."""
    try:
        bot = get_telegram_bot()
        if bot.available:
            bot.send_completion_notification(goal, tasks_count, status)
    except Exception:
        pass


def notify_run_error(
    goal: str,
    error: str,
) -> None:
    """Fire error notifications."""
    try:
        bot = get_telegram_bot()
        if bot.available:
            bot.send_message(
                f"❌ *Run Error*\n\n*Goal:* {goal[:200]}\n*Error:* `{error[:500]}`"
            )
    except Exception:
        pass


def start_all_channels() -> None:
    """Start all configured notification channels. Called once on app startup."""
    try:
        bot = get_telegram_bot()
        if bot.available:
            bot.start()
            print(f"[notifications] Telegram bot started (chat_id={bot.chat_id})", flush=True)
        else:
            print("[notifications] no channels configured (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to enable)", flush=True)
    except Exception as e:
        print(f"[notifications] failed to start: {e}", flush=True)
