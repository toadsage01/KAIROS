"""
FastAPI app — async API + Telegram notification integration.

POST /run and POST /approve enqueue jobs and return immediately with a
job_id. A background worker thread executes the orchestrator serially.
GET /status/{job_id} polls the job. GET /state returns the current
orchestrator state (read from disk, always safe to call).

When the orchestrator pauses at a HITL gate, the Telegram bot (if
configured) sends a message to your phone with inline Approve/Reject
buttons. Tapping a button calls POST /approve, which enqueues a resume
job. The orchestrator picks it up and continues.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.cron import get_cron_manager
from core.jobs import get_job_queue, register_handler
from core.notify import start_all_channels
from core.orchestrator import Orchestrator
from tools.telegram_bot import get_telegram_bot

load_dotenv()

STATE_DIR = os.getenv("MYFORGE_STATE_DIR", "./state")
CONFIG_DIR = os.getenv("MYFORGE_CONFIG_DIR", "./config")

app = FastAPI(title="myforge", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single shared orchestrator instance
_orch: Orchestrator | None = None


def _get_orch() -> Orchestrator:
    global _orch
    if _orch is None:
        _orch = Orchestrator(state_dir=STATE_DIR, config_dir=CONFIG_DIR)
        # Register job handlers — these run in the background worker thread
        register_handler("start", lambda payload: _orch.start(
            payload["goal"], payload.get("workspace_path")
        ).to_dict())
        register_handler("step", lambda payload: _orch.step().to_dict())
        register_handler("approve", lambda payload: _orch.approve(
            payload["gate"], payload.get("decision", "approved"), payload.get("note", "")
        ).to_dict())
        # Initialize the job queue (starts the worker thread)
        get_job_queue(_orch.state)
        # Start notification channels (Telegram bot if configured)
        start_all_channels()
        # Phase 5: register periodic re-index of target_repo (hourly)
        cron = get_cron_manager()
        if cron.available:
            def _reindex():
                _orch._indexed = False
                _orch._ensure_indexed()
            cron.add_job(
                job_id="reindex_target_repo",
                description="Re-index target_repo into vector store + codemap",
                func=_reindex,
                interval_seconds=3600,
            )
    return _orch


# ---------- models ----------
class RunRequest(BaseModel):
    goal: str | None = None  # if None, advance existing run
    workspace_path: str | None = None  # Batch 3: per-run workspace selection


class ApproveRequest(BaseModel):
    gate: str
    decision: Literal["approved", "rejected"] = "approved"
    note: str = ""


# ---------- endpoints ----------
@app.get("/health")
def health():
    # Ensure orchestrator + worker + telegram are initialized
    _get_orch()
    bot = get_telegram_bot()
    return {
        "status": "ok",
        "litellm_available": _litellm_ok(),
        "worker_running": _worker_ok(),
        "telegram_available": bot.available,
    }


@app.post("/run")
def run(req: RunRequest):
    """Enqueue a run job. Returns immediately with the job_id."""
    orch = _get_orch()
    if req.goal:
        payload = {"goal": req.goal}
        if req.workspace_path:
            payload["workspace_path"] = req.workspace_path
        job = get_job_queue().enqueue("start", payload)
    else:
        job = get_job_queue().enqueue("step", {})
    return {
        "job_id": job.id,
        "status": job.status,
        "kind": job.kind,
        "message": f"Job {job.id} queued. Poll GET /status/{job.id} for progress.",
    }


@app.post("/approve")
def approve(req: ApproveRequest):
    """Enqueue an approve job. Returns immediately with the job_id.

    This endpoint is called both by the Streamlit UI AND by the Telegram
    bot when you tap an Approve/Reject button on your phone.
    """
    _get_orch()
    job = get_job_queue().enqueue("approve", {
        "gate": req.gate,
        "decision": req.decision,
        "note": req.note,
    })
    return {
        "job_id": job.id,
        "status": job.status,
        "kind": job.kind,
        "message": f"Approve job {job.id} queued. Poll GET /status/{job.id} for result.",
    }


@app.get("/status/{job_id}")
def job_status(job_id: str):
    """Poll a job's status."""
    job = get_job_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job.to_dict()


class BTWRequest(BaseModel):
    message: str


@app.post("/btw")
def btw(req: BTWRequest):
    """Queue a /btw side note for the next agent turn.

    The orchestrator reads state/btw_queue.json before each agent call
    and injects the notes into the agent's prompt.
    """
    import json
    from pathlib import Path
    orch = _get_orch()
    btw_path = orch.state.root / "btw_queue.json"
    queue = []
    if btw_path.exists():
        try:
            queue = json.loads(btw_path.read_text(encoding="utf-8"))
        except Exception:
            queue = []
    queue.append({"message": req.message, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
    btw_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    return {"status": "queued", "queue_length": len(queue)}


@app.get("/jobs")
def list_jobs(limit: int = 20):
    """List recent jobs."""
    _get_orch()
    jq = get_job_queue()
    return {
        "current_job_id": jq.current_job_id,
        "jobs": [j.to_dict() for j in jq.list_jobs(limit=limit)],
    }


@app.get("/state")
def get_state():
    """Full state snapshot. Always safe to call."""
    orch = _get_orch()
    snap = orch.state.snapshot()
    rs = orch.state.read_json("tasks")
    jq = get_job_queue()
    bot = get_telegram_bot()
    return {
        "run": rs,
        "files": snap,
        "current_job_id": jq.current_job_id,
        "recent_jobs": [j.to_dict() for j in jq.list_jobs(limit=5)],
        "telegram_available": bot.available,
    }


@app.get("/logs")
def logs(tail: int = 200):
    orch = _get_orch()
    return {"log": orch.state.read_log(tail=tail)}


@app.get("/router_log")
def router_log(tail: int = 200):
    p = Path("logs/router.log")
    if not p.exists():
        return {"log": ""}
    lines = p.read_text(encoding="utf-8").splitlines()
    return {"log": "\n".join(lines[-tail:])}


@app.get("/cron")
def cron_status():
    return get_cron_manager().status()


@app.get("/notify")
def notify_status():
    """Status of notification channels."""
    bot = get_telegram_bot()
    return {
        "telegram": {
            "available": bot.available,
            "chat_id": bot.chat_id if bot.available else None,
        },
    }


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    """Cancel a queued job."""
    ok = get_job_queue().cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="job not cancellable")
    return {"status": "cancelled", "job_id": job_id}


@app.post("/reset")
def reset():
    """Wipe all state."""
    global _orch
    orch = _get_orch()
    import shutil
    p = Path(STATE_DIR)
    if p.exists():
        for sub in p.iterdir():
            if sub.is_file():
                sub.unlink()
            elif sub.is_dir():
                shutil.rmtree(sub)
    logs_p = p.parent / "logs"
    if logs_p.exists():
        shutil.rmtree(logs_p)
    _orch = None
    return {"status": "reset"}


def _litellm_ok() -> bool:
    try:
        import litellm  # noqa: F401
        return True
    except ImportError:
        return False


def _worker_ok() -> bool:
    try:
        jq = get_job_queue()
        return jq._worker is not None and jq._worker.is_alive()
    except Exception:
        return False


# ---------- WebSocket for real-time streaming ----------
@app.websocket("/ws")
async def websocket_endpoint(websocket):
    """WebSocket endpoint for real-time state updates.

    The TUI connects to this instead of polling /state every 2 seconds.
    Server pushes updates whenever state changes.

    Message format:
      {"type": "state", "data": {...}}
      {"type": "log", "data": "log line"}
      {"type": "router_log", "data": "log line"}
    """
    import asyncio
    import json

    await websocket.accept()
    orch = _get_orch()
    last_log_size = 0
    last_router_log_size = 0

    try:
        while True:
            # Push current state
            snap = orch.state.snapshot()
            rs = orch.state.read_json("tasks")
            data = {
                "run": rs,
                "files": snap,
                "current_job_id": get_job_queue().current_job_id,
                "recent_jobs": [j.to_dict() for j in get_job_queue().list_jobs(limit=5)],
            }
            await websocket.send_json({"type": "state", "data": data})

            # Push new log lines (only if changed)
            log_text = snap.get("log", "")
            if len(log_text) > last_log_size:
                new_lines = log_text[last_log_size:]
                await websocket.send_json({"type": "log", "data": new_lines})
                last_log_size = len(log_text)

            # Push new router log lines
            router_log_path = Path("logs/router.log")
            if router_log_path.exists():
                router_text = router_log_path.read_text(encoding="utf-8")
                if len(router_text) > last_router_log_size:
                    new_router = router_text[last_router_log_size:]
                    await websocket.send_json({"type": "router_log", "data": new_router})
                    last_router_log_size = len(router_text)

            await asyncio.sleep(1)  # Push every 1 second
    except Exception:
        pass  # Connection closed


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("MYFORGE_HOST", "0.0.0.0"),
        port=int(os.getenv("MYFORGE_API_PORT", "8000")),
    )
