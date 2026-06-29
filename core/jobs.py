"""
Async job queue for the orchestrator.

The orchestrator's step() / approve() calls can take 30-90+ seconds with
real LLMs. We can't block HTTP requests on them. Instead:

  - POST /run and POST /approve enqueue a Job
  - A single background worker thread processes jobs serially
  - GET /status/{job_id} returns the current orchestrator state (read-only)

This is intentionally simple — no asyncio, no task framework, just a
Queue + a Thread. Serial execution is correct here: the orchestrator
mutates state/tasks.json and we don't want two runs clobbering each other.

For Kairos future: this is the foundation for mobile HITL. When the
orchestrator pauses at a HITL gate, the worker thread is idle (not
blocked) — it has finished its job. A future Telegram bot can hit
POST /approve from your phone, enqueuing a new job to resume.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from core.state import FileState


JobStatus = Literal["queued", "running", "done", "error", "cancelled"]


@dataclass
class Job:
    id: str
    kind: str  # "start" | "step" | "approve"
    payload: dict[str, Any]
    status: JobStatus = "queued"
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "payload": self.payload,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class JobQueue:
    """Single-worker job queue. Jobs run in a background thread, serially.

    Why single worker? The orchestrator mutates state/tasks.json. Concurrent
    runs would clobber each other. Serial execution is correct.

    Why not asyncio? The orchestrator code is synchronous (file I/O + LLM
    calls). Wrapping in asyncio would require rewriting it. A thread + queue
    is simpler and works.
    """

    def __init__(self, state: FileState):
        self.state = state
        self._queue: queue.Queue[Job] = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._current_job_id: str | None = None

    # ---------- lifecycle ----------
    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        # Send a sentinel to unblock the queue.get()
        self._queue.put(None)  # type: ignore[arg-type]
        if self._worker:
            self._worker.join(timeout=5.0)

    # ---------- public API ----------
    def enqueue(self, kind: str, payload: dict[str, Any] | None = None) -> Job:
        """Add a job to the queue. Returns the Job immediately."""
        job = Job(
            id=str(uuid.uuid4())[:8],
            kind=kind,
            payload=payload or {},
            created_at=_ts(),
        )
        with self._lock:
            self._jobs[job.id] = job
        self.state.append_log(f"job queued: id={job.id} kind={kind}")
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        # Most recent first
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued job. Can't cancel running jobs (would corrupt state)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status != "queued":
                return False
            job.status = "cancelled"
            job.finished_at = _ts()
        return True

    @property
    def current_job_id(self) -> str | None:
        return self._current_job_id

    # ---------- internal ----------
    def _run_loop(self) -> None:
        """Worker loop. Pulls jobs from the queue and executes them."""
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:  # stop sentinel
                break
            if job.status == "cancelled":
                continue

            with self._lock:
                self._current_job_id = job.id
                job.status = "running"
                job.started_at = _ts()

            try:
                # The actual work is done by a callback registered by the
                # orchestrator. We just manage the lifecycle here.
                handler = _JOB_HANDLERS.get(job.kind)
                if handler is None:
                    raise RuntimeError(f"no handler for job kind: {job.kind}")
                result = handler(job.payload)
                with self._lock:
                    job.status = "done"
                    job.result = result
                    job.finished_at = _ts()
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    job.status = "error"
                    job.error = f"{type(e).__name__}: {e}"
                    job.finished_at = _ts()
                self.state.append_log(f"job error: id={job.id} err={e}")
            finally:
                with self._lock:
                    self._current_job_id = None

        # cleanup
        with self._lock:
            self._current_job_id = None


# ---------- job handlers ----------
# These are registered by the FastAPI app at startup, because they need
# access to the orchestrator instance.
_JOB_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def register_handler(kind: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    _JOB_HANDLERS[kind] = fn


# ---------- singleton ----------
_singleton: JobQueue | None = None
_lock = threading.Lock()


def get_job_queue(state: FileState | None = None) -> JobQueue:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                if state is None:
                    raise RuntimeError("JobQueue not initialized — pass state on first call")
                _singleton = JobQueue(state)
                _singleton.start()
    return _singleton
