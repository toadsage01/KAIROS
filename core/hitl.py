"""
HITL — human-in-the-loop gates.

A HITL gate is just a pause in the DAG. The orchestrator, when it reaches
a hitl node, writes state/hitl/{gate}.json with status="pending" and
returns control to the caller. The caller (UI, API, cron) is responsible
for writing status="approved" or status="rejected" to resume.

There is no long-running server thread waiting. The orchestrator is
resumable: on the next /run call after a gate is resolved, it picks up
where it left off by reading state/tasks.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

from .state import FileState

GateStatus = Literal["pending", "approved", "rejected"]


class HITLManager:
    def __init__(self, state: FileState):
        self.state = state

    def request(self, gate: str, payload: dict | None = None) -> dict:
        """Mark a gate as pending. Returns the gate record."""
        rec = {
            "gate": gate,
            "status": "pending",
            "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "resolved_at": None,
            "payload": payload or {},
        }
        self.state.write_json(gate, rec, subdir="hitl")
        return rec

    def status(self, gate: str) -> GateStatus | None:
        rec = self.state.read_json(gate, subdir="hitl")
        return rec.get("status") if rec else None

    def resolve(self, gate: str, decision: GateStatus, note: str = "") -> dict:
        rec = self.state.read_json(gate, subdir="hitl") or {
            "gate": gate,
            "payload": {},
        }
        rec["status"] = decision
        rec["resolved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        rec["note"] = note
        self.state.write_json(gate, rec, subdir="hitl")
        return rec

    def reset(self, gate: str) -> None:
        """Clear a gate so the next run can re-request it."""
        p = self.state.root / "hitl" / f"{gate}.json"
        if p.exists():
            p.unlink()
