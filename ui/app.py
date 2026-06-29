"""
Streamlit UI for myforge — async polling edition.

POST /run and POST /approve return immediately with a job_id. The UI
polls GET /state every 2-3 seconds to see current orchestrator status.
No more httpx.ReadTimeout. No more frozen UI. No more double-click chaos.

This is the foundation for Kairos: once the UI polls instead of blocks,
we can add mobile HITL (Telegram bot hits /approve from your phone,
UI sees the state change on next poll).
"""
from __future__ import annotations

import os
import time

import httpx
import streamlit as st

API = os.getenv("MYFORGE_API_URL", "http://localhost:8000")

# Timeouts — /run and /approve now return instantly, so 10s is plenty.
# /state is metadata-only, 5s is fine.
TIMEOUT_FAST = 5.0
TIMEOUT_API = 15.0  # for /run, /approve (they enqueue and return)

st.set_page_config(page_title="myforge", page_icon="🔨", layout="wide")

# ---------- sidebar ----------
with st.sidebar:
    st.header("myforge")
    st.caption("file-driven DAG · async · no agent chatter")

    try:
        health = httpx.get(f"{API}/health", timeout=TIMEOUT_FAST).json()
        st.success(f"API: {health['status']}")
        if not health.get("litellm_available"):
            st.warning("litellm not installed — running in mock mode")
        if not health.get("worker_running"):
            st.error("background worker not running!")
    except Exception as e:  # noqa: BLE001
        st.error(f"API unreachable: {e}")
        st.stop()

    st.divider()
    goal = st.text_area(
        "Goal",
        height=100,
        placeholder="e.g. add a power(a, b) function to calculator.py",
    )

    if st.button("▶ Start run", type="primary", disabled=not goal.strip()):
        try:
            r = httpx.post(f"{API}/run", json={"goal": goal}, timeout=TIMEOUT_API)
            r.raise_for_status()
            data = r.json()
            st.success(f"Job queued: {data['job_id']}")
        except Exception as e:  # noqa: BLE001
            st.error(f"start failed: {e}")
        st.rerun()

    if st.button("⏭ Step (advance one node)"):
        try:
            r = httpx.post(f"{API}/run", json={}, timeout=TIMEOUT_API)
            r.raise_for_status()
            data = r.json()
            st.info(f"Step job queued: {data['job_id']}")
        except Exception as e:  # noqa: BLE001
            st.error(f"step failed: {e}")
        st.rerun()

    if st.button("🔄 Refresh now"):
        st.rerun()

    st.divider()
    if st.button("🗑 Reset state (dev)", type="secondary"):
        st.session_state["confirm_reset"] = True

    if st.session_state.get("confirm_reset"):
        st.warning("Are you sure? This wipes ALL state.")
        c1, c2 = st.columns(2)
        if c1.button("Yes, wipe", type="primary"):
            try:
                httpx.post(f"{API}/reset", timeout=TIMEOUT_API)
                st.session_state.clear()
                st.success("reset")
            except Exception as e:  # noqa: BLE001
                st.error(f"reset failed: {e}")
            st.rerun()
        if c2.button("Cancel"):
            st.session_state.pop("confirm_reset", None)
            st.rerun()

# ---------- main ----------
st.title("myforge")

# Fetch current state — this is the only blocking call and it's fast
try:
    state = httpx.get(f"{API}/state", timeout=TIMEOUT_FAST).json()
except Exception as e:  # noqa: BLE001
    st.error(f"failed to load state: {e}")
    st.stop()

run = state.get("run") or {}
files = state.get("files") or {}
current_job_id = state.get("current_job_id")
recent_jobs = state.get("recent_jobs", [])

# status banner
status = run.get("status", "(no run)")
status_color = {
    "running": "info",
    "paused": "warning",
    "done": "success",
    "error": "error",
}.get(status, "info")

# Show job activity if any
if current_job_id:
    status_msg = (
        f"**Status:** `{status}`  ·  **Node:** `{run.get('current_node_id', '-')}`  ·  "
        f"**Task idx:** {run.get('current_task_index', 0)}/{len(run.get('tasks', []))}  ·  "
        f"🔄 Job `{current_job_id}` running..."
    )
else:
    status_msg = (
        f"**Status:** `{status}`  ·  **Node:** `{run.get('current_node_id', '-')}`  ·  "
        f"**Task idx:** {run.get('current_task_index', 0)}/{len(run.get('tasks', []))}"
    )
getattr(st, status_color)(status_msg)

if run.get("last_error"):
    st.error(f"last_error: {run['last_error']}")

# Recent jobs strip (collapsible)
if recent_jobs:
    with st.expander(f"Recent jobs ({len(recent_jobs)})", expanded=False):
        for j in recent_jobs:
            emoji = {
                "queued": "⏳", "running": "🔄", "done": "✅",
                "error": "❌", "cancelled": "🚫",
            }.get(j["status"], "?")
            st.write(
                f"{emoji} `{j['id']}` {j['kind']} — {j['status']}  ·  "
                f"created {j['created_at']}"
            )
            if j.get("error"):
                st.code(j["error"], language="text")

# HITL panel — buttons are now safe to click (they enqueue, don't block)
current_node = run.get("current_node_id")
if status == "paused":
    gate = current_node
    hitl_files = files.get("hitl", {})
    gate_name = next(iter(hitl_files.keys()), current_node).replace(".json", "")
    st.warning(f"⏸ Paused at HITL gate: `{gate_name}`")

    c1, c2 = st.columns(2)
    if c1.button("✅ Approve", type="primary"):
        try:
            r = httpx.post(
                f"{API}/approve",
                json={"gate": gate_name, "decision": "approved"},
                timeout=TIMEOUT_API,
            )
            r.raise_for_status()
            data = r.json()
            st.success(f"Approve job queued: {data['job_id']}")
        except Exception as e:  # noqa: BLE001
            st.error(f"approve failed: {e}")
        st.rerun()
    if c2.button("❌ Reject"):
        try:
            r = httpx.post(
                f"{API}/approve",
                json={"gate": gate_name, "decision": "rejected"},
                timeout=TIMEOUT_API,
            )
            r.raise_for_status()
            data = r.json()
            st.info(f"Reject job queued: {data['job_id']}")
        except Exception as e:  # noqa: BLE001
            st.error(f"reject failed: {e}")
        st.rerun()

# tabs for state files
tab_names = ["Goal", "Plan", "Tasks", "Changes", "Review", "Research", "Log",
             "Router Log", "Cron", "Jobs"]
tabs = st.tabs(tab_names)

with tabs[0]:
    g = files.get("root", {}).get("goal.md")
    st.markdown(g or "_(no goal set)_")

with tabs[1]:
    p = files.get("root", {}).get("plan.md")
    st.markdown(p or "_(no plan yet — run the thinker)_")

with tabs[2]:
    tasks = run.get("tasks", [])
    if not tasks:
        st.caption("no tasks parsed yet")
    else:
        for i, t in enumerate(tasks):
            cur = "👉 " if i == run.get("current_task_index") else "   "
            st.markdown(f"{cur}**{t.get('id', '?')}** — {t.get('title', '')}")
            st.caption(
                f"needs_research={t.get('needs_research', False)}  ·  "
                f"files={t.get('files', '')}"
            )

with tabs[3]:
    changes = files.get("changes", {})
    if not changes:
        st.caption("no changes yet")
    for name, content in changes.items():
        with st.expander(name, expanded=True):
            st.code(content, language="markdown")

with tabs[4]:
    reviews = files.get("review", {})
    if not reviews:
        st.caption("no reviews yet")
    for name, content in reviews.items():
        with st.expander(name, expanded=True):
            st.markdown(content)

with tabs[5]:
    research = files.get("research", {})
    if not research:
        st.caption("no research yet")
    for name, content in research.items():
        with st.expander(name, expanded=True):
            st.markdown(content)

with tabs[6]:
    log = files.get("log", "")
    st.code(log, language="text")

with tabs[7]:
    try:
        r = httpx.get(f"{API}/router_log?tail=100", timeout=TIMEOUT_FAST).json()
        st.code(r.get("log", ""), language="text")
    except Exception as e:  # noqa: BLE001
        st.error(f"failed: {e}")

with tabs[8]:
    try:
        c = httpx.get(f"{API}/cron", timeout=TIMEOUT_FAST).json()
        st.write(
            f"**available:** `{c.get('available')}`  ·  "
            f"**started:** `{c.get('started')}`"
        )
        for j in c.get("jobs", []):
            with st.expander(f"{j['id']} (every {j['interval_seconds']}s)"):
                st.write(f"**description:** {j['description']}")
                st.write(f"**last_run:** `{j['last_run']}`")
                st.write(f"**last_status:** `{j['last_status']}`")
                st.write(f"**runs:** {j['runs']}")
    except Exception as e:  # noqa: BLE001
        st.error(f"failed: {e}")

with tabs[9]:
    try:
        r = httpx.get(f"{API}/jobs?limit=20", timeout=TIMEOUT_FAST).json()
        st.write(f"**current_job_id:** `{r.get('current_job_id')}`")
        for j in r.get("jobs", []):
            emoji = {
                "queued": "⏳", "running": "🔄", "done": "✅",
                "error": "❌", "cancelled": "🚫",
            }.get(j["status"], "?")
            with st.expander(f"{emoji} `{j['id']}` {j['kind']} — {j['status']}"):
                st.write(f"**created:** {j['created_at']}")
                st.write(f"**started:** {j['started_at']}")
                st.write(f"**finished:** {j['finished_at']}")
                if j.get("error"):
                    st.code(j["error"], language="text")
                if j.get("result"):
                    st.json(j["result"])
                if j["status"] == "queued":
                    if st.button(f"Cancel {j['id']}", key=f"cancel_{j['id']}"):
                        try:
                            httpx.post(f"{API}/cancel/{j['id']}", timeout=TIMEOUT_API)
                            st.success("cancelled")
                        except Exception as e:  # noqa: BLE001
                            st.error(f"cancel failed: {e}")
                        st.rerun()
    except Exception as e:  # noqa: BLE001
        st.error(f"failed: {e}")

# auto-refresh: poll whenever there's activity
# - running: orchestrator is executing → poll every 2s
# - paused AND a job is queued/running (approve just clicked): poll every 2s
# - paused AND no job: poll every 5s (in case external approver — future mobile HITL)
# - done/error: don't poll (user can hit Refresh)
if status == "running":
    time.sleep(2)
    st.rerun()
elif current_job_id:
    # A job is in flight (e.g. approve just clicked, orchestrator resuming)
    time.sleep(2)
    st.rerun()
elif status == "paused":
    # Idle pause — poll slower, in case something external changes the gate
    time.sleep(5)
    st.rerun()
