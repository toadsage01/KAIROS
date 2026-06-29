"""
Phase 5 — scheduled background tasks via APScheduler.

The only scheduled task in v1 is "re-index target_repo every hour" so
the vector store + codemap stay fresh as files change outside myforge.

Graceful degradation: if APScheduler isn't installed, the scheduler is
a no-op and cron_status() reports available=False. The rest of the app
keeps working.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
    from apscheduler.triggers.interval import IntervalTrigger  # type: ignore
    _HAS_APS = True
except ImportError:
    BackgroundScheduler = None  # type: ignore
    IntervalTrigger = None  # type: ignore
    _HAS_APS = False


@dataclass
class CronJob:
    id: str
    description: str
    interval_seconds: int
    last_run: str = ""
    last_status: str = "never"
    runs: int = 0


@dataclass
class CronManager:
    """Owns the background scheduler. Singleton per process."""
    jobs: dict[str, CronJob] = field(default_factory=dict)
    _scheduler: Any = None
    _started: bool = False

    @property
    def available(self) -> bool:
        return _HAS_APS

    def add_job(self, job_id: str, description: str, func: Callable,
                interval_seconds: int) -> CronJob:
        """Register a recurring job. If APScheduler is unavailable, the
        job is recorded but never runs (cron_status still shows it)."""
        job = CronJob(id=job_id, description=description,
                      interval_seconds=interval_seconds)
        self.jobs[job_id] = job
        if self.available:
            if self._scheduler is None:
                self._scheduler = BackgroundScheduler()
            if not self._started:
                self._scheduler.start()
                self._started = True
            self._scheduler.add_job(
                self._wrap(job_id, func),
                trigger=IntervalTrigger(seconds=interval_seconds),
                id=job_id,
                replace_existing=True,
            )
        return job

    def _wrap(self, job_id: str, func: Callable) -> Callable:
        def runner():
            job = self.jobs.get(job_id)
            if job:
                job.last_run = time.strftime("%Y-%m-%dT%H:%M:%S")
                job.runs += 1
            try:
                func()
                if job:
                    job.last_status = "ok"
            except Exception as e:  # noqa: BLE001
                if job:
                    job.last_status = f"error: {e}"
        return runner

    def remove_job(self, job_id: str) -> bool:
        if job_id in self.jobs and self.available and self._scheduler:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        return self.jobs.pop(job_id, None) is not None

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "started": self._started,
            "jobs": [
                {
                    "id": j.id, "description": j.description,
                    "interval_seconds": j.interval_seconds,
                    "last_run": j.last_run, "last_status": j.last_status,
                    "runs": j.runs,
                }
                for j in self.jobs.values()
            ],
        }

    def shutdown(self) -> None:
        if self._scheduler and self._started:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass


# Module-level singleton — shared by the API and orchestrator
_singleton: CronManager | None = None
_lock = threading.Lock()


def get_cron_manager() -> CronManager:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = CronManager()
    return _singleton
