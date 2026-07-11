"""
Streamlit UI for myforge — gets you running in 2 hours, not 2 days.

Layout:
  - Left: goal input, "Start run" button, current DAG status
  - Center: tabbed view of goal.md / plan.md / current task's changes & review
  - Right: HITL approve/reject buttons + log tail

The UI polls /state every 2s when a run is active. It calls /run to advance
one step at a time — the server is stateless.
"""
from __future__ import annotations

import os
import time

import httpx
import streamlit as st

API = os.getenv("MYFORGE_API_URL", "http://localhost:8000")

st.set_page_config(page_title="myforge", page_icon="🔨", layout="wide")

# ---------- sidebar ----------
with st.sidebar:
    st.header("myforge")
    st.caption("file-driven DAG · no agent chatter")
    try:
        health = httpx.get(f"{API}/health", timeout=3.0).json()
        st.success(f"API: {health['status']}")
        if not health.get("litellm_available"):
            st.warning("litellm not installed — running in mock mode")
    except Exception as e:  # noqa: BLE001
        st.error(f"API unreachable: {e}")
        st.stop()

    st.divider()
    goal = st.text_area("Goal", height=100, placeholder="e.g. add a /health endpoint to api/main.py")
    
    # Batch 3: per-run workspace selection
    workspace_path = st.text_input(
        "Workspace folder (optional)",
        placeholder="e.g. /home/manas/Projects/my_project (leave blank for default)",
        help="Path to the repo where the agent should work. Leave blank to use MYFORGE_TARGET_REPO from .env",
    )
    
    if st.button("▶ Start run", type="primary", disabled=not goal.strip()):
        try:
            payload = {"goal": goal}
            if workspace_path.strip():
                payload["workspace_path"] = workspace_path.strip()
            r = httpx.post(f"{API}/run", json=payload, timeout=30.0)
            r.raise_for_status()
            st.session_state["last_run"] = r.json()
            st.success("Run started")
        except Exception as e:  # noqa: BLE001
            st.error(f"start failed: {e}")

    if st.button("⏭ Step (advance one node)"):
        try:
            r = httpx.post(f"{API}/run", json={}, timeout=30.0)
            st.session_state["last_run"] = r.json()
        except Exception as e:  # noqa: BLE001
            st.error(f"step failed: {e}")

    if st.button("🔄 Refresh state"):
        st.session_state.pop("last_state", None)

    st.divider()
    if st.button("🗑 Reset state (dev)"):
        httpx.post(f"{API}/reset", timeout=5.0)
        st.session_state.clear()
        st.success("reset")

# ---------- main ----------
st.title("myforge")

try:
    state = httpx.get(f"{API}/state", timeout=5.0).json()
except Exception as e:  # noqa: BLE001
    st.error(f"failed to load state: {e}")
    st.stop()

run = state.get("run") or {}
files = state.get("files") or {}

# status banner
status = run.get("status", "(no run)")
color = {
    "running": "info",
    "paused": "warning",
    "done": "success",
    "error": "error",
}.get(status, "info")
getattr(st, color)(f"**Status:** `{status}`  ·  **Node:** `{run.get('current_node_id', '-')}`  ·  **Task idx:** {run.get('current_task_index', 0)}/{len(run.get('tasks', []))}")

if run.get("last_error"):
    st.error(f"last_error: {run['last_error']}")

# HITL panel
current_node = run.get("current_node_id")
if status == "paused":
    gate = current_node  # by convention, the hitl node id == gate name lookup
    # Try to find the gate name from the hitl subdir
    hitl_files = files.get("hitl", {})
    gate_name = next(iter(hitl_files.keys()), current_node).replace(".json", "")
    st.warning(f"⏸ Paused at HITL gate: `{gate_name}`")
    c1, c2 = st.columns(2)
    if c1.button("✅ Approve", type="primary"):
        httpx.post(f"{API}/approve",
                   json={"gate": gate_name, "decision": "approved"}, timeout=10.0)
        st.rerun()
    if c2.button("❌ Reject"):
        httpx.post(f"{API}/approve",
                   json={"gate": gate_name, "decision": "rejected"}, timeout=10.0)
        st.rerun()

# tabs for state files
tab_names = ["Goal", "Plan", "Tasks", "Changes", "Review", "Research", "Log",
             "Router Log", "Cron"]
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
            st.caption(f"needs_research={t.get('needs_research', False)}  ·  files={t.get('files', '')}")

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
        r = httpx.get(f"{API}/router_log?tail=100", timeout=5.0).json()
        st.code(r.get("log", ""), language="text")
    except Exception as e:  # noqa: BLE001
        st.error(f"failed: {e}")

with tabs[8]:
    try:
        c = httpx.get(f"{API}/cron", timeout=5.0).json()
        st.write(f"**available:** `{c.get('available')}`  ·  **started:** `{c.get('started')}`")
        for j in c.get("jobs", []):
            with st.expander(f"{j['id']} (every {j['interval_seconds']}s)"):
                st.write(f"**description:** {j['description']}")
                st.write(f"**last_run:** `{j['last_run']}`")
                st.write(f"**last_status:** `{j['last_status']}`")
                st.write(f"**runs:** {j['runs']}")
    except Exception as e:  # noqa: BLE001
        st.error(f"failed: {e}")

# auto-refresh when running
if status == "running":
    time.sleep(2)
    st.rerun()
