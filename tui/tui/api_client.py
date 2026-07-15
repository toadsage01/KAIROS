"""
API Client — connects to Kairos FastAPI backend.

Polls /state every 2 seconds for real-time updates.
Sends /run, /approve, /reset commands via httpx.

This is the TUI's only connection to the backend — same endpoints
that Streamlit used, just consumed by Textual instead.
"""
from __future__ import annotations

import os
from typing import Any

import httpx


class ApiClient:
    """Client for the Kairos FastAPI backend."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv(
            "MYFORGE_API_URL", "http://localhost:8000"
        )
        self._client = httpx.Client(timeout=10.0)

    def health(self) -> dict[str, Any]:
        """Check if the API is running."""
        try:
            r = self._client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_state(self) -> dict[str, Any]:
        """Get full state snapshot. Called every 2 seconds by TUI."""
        try:
            r = self._client.get(f"{self.base_url}/state")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def start_run(self, goal: str, workspace_path: str | None = None) -> dict:
        """Start a new run with a goal."""
        payload: dict[str, Any] = {"goal": goal}
        if workspace_path:
            payload["workspace_path"] = workspace_path
        try:
            r = self._client.post(
                f"{self.base_url}/run", json=payload, timeout=15.0
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def step(self) -> dict:
        """Advance the run by one step."""
        try:
            r = self._client.post(
                f"{self.base_url}/run", json={}, timeout=15.0
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def approve(self, gate: str, decision: str = "approved") -> dict:
        """Approve or reject a HITL gate."""
        try:
            r = self._client.post(
                f"{self.base_url}/approve",
                json={"gate": gate, "decision": decision},
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_logs(self, tail: int = 50) -> str:
        """Get orchestrator log tail."""
        try:
            r = self._client.get(
                f"{self.base_url}/logs", params={"tail": tail}
            )
            r.raise_for_status()
            return r.json().get("log", "")
        except Exception:
            return ""

    def get_router_log(self, tail: int = 50) -> str:
        """Get router log tail (model fallback events)."""
        try:
            r = self._client.get(
                f"{self.base_url}/router_log", params={"tail": tail}
            )
            r.raise_for_status()
            return r.json().get("log", "")
        except Exception:
            return ""

    def reset(self) -> dict:
        """Reset all state."""
        try:
            r = self._client.post(f"{self.base_url}/reset", timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def close(self):
        self._client.close()
