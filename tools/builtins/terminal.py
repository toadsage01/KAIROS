"""
Terminal tools — execute (sanitized), background_job.

execute: Run a shell command within the workspace. Commands are classified
by tools/permissions.py — SAFE commands run immediately, MODERATE commands
run within the worktree, DANGEROUS commands require HITL approval.

background_job: Start a long-running command (e.g. dev server) without
blocking. Returns a job ID that can be checked later.
"""
from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from tools.base import BaseTool, ToolContext, ToolPermission, ToolResult
from tools.permissions import classify_command


class ExecuteTool(BaseTool):
    name = "execute"
    description = (
        "Execute a shell command in the workspace. Read-only commands "
        "(ls, cat, pytest, ruff) run immediately. Write commands "
        "(git commit, pip install) run within the worktree. Destructive "
        "commands (rm, git reset --hard) require approval."
    )
    schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 30, max 300)",
            },
        },
        "required": ["command"],
    }
    permission = ToolPermission.MODERATE  # classified per-command at runtime

    def execute(self, ctx: ToolContext, command: str, timeout: int = 30) -> ToolResult:
        if not command or not command.strip():
            return ToolResult(success=False, output="", error="empty command")

        # Clamp timeout
        timeout = max(1, min(timeout, 300))

        # Classify the command
        perm = classify_command(command)

        # DANGEROUS commands require HITL approval (handled by registry)
        # But we also check here for defense in depth
        if perm == ToolPermission.DANGEROUS:
            # The registry should have already checked HITL approval
            # If we get here without approval, deny
            return ToolResult(
                success=False,
                output="",
                error=f"command classified as DANGEROUS: '{command}'. "
                      f"This requires HITL approval. If you got here, the "
                      f"approval callback is not set or denied the request.",
            )

        # Determine working directory
        cwd = ctx.worktree_path or ctx.workspace_path
        if not cwd.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"workspace directory does not exist: {cwd}",
            )

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # Truncate large outputs
            stdout = result.stdout
            stderr = result.stderr
            if len(stdout) > 10000:
                stdout = stdout[:10000] + f"\n... (truncated, {len(result.stdout)} chars total)"
            if len(stderr) > 5000:
                stderr = stderr[:5000] + f"\n... (truncated, {len(result.stderr)} chars total)"

            output = ""
            if stdout:
                output += f"STDOUT:\n{stdout}\n"
            if stderr:
                output += f"STDERR:\n{stderr}\n"
            output += f"EXIT CODE: {result.returncode}"

            return ToolResult(
                success=result.returncode == 0,
                output=output,
                data={
                    "exit_code": result.returncode,
                    "permission": perm.value,
                    "cwd": str(cwd),
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"command timed out after {timeout}s: {command}",
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))


class BackgroundJobTool(BaseTool):
    name = "background_job"
    description = (
        "Start a long-running command in the background (e.g. dev server, "
        "file watcher). Returns a job ID. Use 'check_background_job' to "
        "check status. Useful for commands that shouldn't block the agent."
    )
    schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run in background",
            },
        },
        "required": ["command"],
    }
    permission = ToolPermission.MODERATE

    # Class-level registry of background jobs
    _jobs: dict[str, dict[str, Any]] = {}

    def execute(self, ctx: ToolContext, command: str) -> ToolResult:
        if not command or not command.strip():
            return ToolResult(success=False, output="", error="empty command")

        perm = classify_command(command)
        if perm == ToolPermission.DANGEROUS:
            return ToolResult(
                success=False,
                output="",
                error=f"command classified as DANGEROUS — not allowed in background",
            )

        cwd = ctx.worktree_path or ctx.workspace_path
        job_id = str(uuid.uuid4())[:8]

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._jobs[job_id] = {
                "pid": proc.pid,
                "process": proc,
                "command": command,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "cwd": str(cwd),
            }
            return ToolResult(
                success=True,
                output=f"started background job {job_id} (pid={proc.pid}): {command}",
                data={"job_id": job_id, "pid": proc.pid},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))

    @classmethod
    def check_job(cls, job_id: str) -> dict[str, Any] | None:
        """Check the status of a background job."""
        job = cls._jobs.get(job_id)
        if job is None:
            return None
        proc = job["process"]
        poll = proc.poll()
        return {
            "job_id": job_id,
            "pid": job["pid"],
            "command": job["command"],
            "started_at": job["started_at"],
            "running": poll is None,
            "exit_code": poll,
        }

    @classmethod
    def stop_job(cls, job_id: str) -> bool:
        """Stop a background job."""
        job = cls._jobs.get(job_id)
        if job is None:
            return False
        try:
            job["process"].terminate()
            job["process"].wait(timeout=5)
        except Exception:
            try:
                job["process"].kill()
            except Exception:
                pass
        return True
