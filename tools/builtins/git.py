"""
Git tools — status, diff, log, commit, branch.

All git tools operate on the worktree (if set) or the workspace root.
Read-only operations (status, diff, log) are SAFE. Write operations
(commit, branch) are MODERATE.
"""
from __future__ import annotations

import subprocess
from typing import Any

from tools.base import BaseTool, ToolContext, ToolPermission, ToolResult


def _run_git(cwd, *args: str) -> tuple[int, str, str]:
    """Run a git command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "git command timed out"
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


class GitStatusTool(BaseTool):
    name = "git_status"
    description = (
        "Show the working tree status — staged, unstaged, and untracked files. "
        "Read-only."
    )
    schema = {
        "type": "object",
        "properties": {},
    }
    permission = ToolPermission.SAFE

    def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        cwd = ctx.worktree_path or ctx.workspace_path
        code, stdout, stderr = _run_git(cwd, "status", "--short")
        if code != 0:
            return ToolResult(success=False, output="", error=stderr or "git status failed")
        return ToolResult(success=True, output=stdout or "(clean working tree)")


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = (
        "Show changes between commits, working tree, and index. "
        "Use staged=true to show only staged changes. Read-only."
    )
    schema = {
        "type": "object",
        "properties": {
            "staged": {
                "type": "boolean",
                "description": "If true, show only staged changes (default false)",
            },
            "path": {
                "type": "string",
                "description": "Optional: restrict to a specific file path",
            },
        },
    }
    permission = ToolPermission.SAFE

    def execute(self, ctx: ToolContext, staged: bool = False, path: str = "") -> ToolResult:
        cwd = ctx.worktree_path or ctx.workspace_path
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.append("--")
            args.append(path)
        code, stdout, stderr = _run_git(cwd, *args)
        if code != 0:
            return ToolResult(success=False, output="", error=stderr or "git diff failed")
        return ToolResult(success=True, output=stdout or "(no changes)")


class GitLogTool(BaseTool):
    name = "git_log"
    description = (
        "Show commit history. Returns the last N commits with hash, "
        "author, date, and message. Read-only."
    )
    schema = {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of commits to show (default 10, max 50)",
            },
            "oneline": {
                "type": "boolean",
                "description": "If true, show one line per commit (default true)",
            },
        },
    }
    permission = ToolPermission.SAFE

    def execute(self, ctx: ToolContext, count: int = 10, oneline: bool = True) -> ToolResult:
        count = max(1, min(count, 50))
        cwd = ctx.worktree_path or ctx.workspace_path
        args = ["log", f"-{count}"]
        if oneline:
            args.append("--oneline")
        code, stdout, stderr = _run_git(cwd, *args)
        if code != 0:
            return ToolResult(success=False, output="", error=stderr or "git log failed")
        return ToolResult(success=True, output=stdout or "(no commits)")


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = (
        "Stage all changes and create a commit. This runs 'git add -A' "
        "followed by 'git commit -m <message>'. Modifies the repository."
    )
    schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message",
            },
        },
        "required": ["message"],
    }
    permission = ToolPermission.MODERATE

    def execute(self, ctx: ToolContext, message: str) -> ToolResult:
        if not message or not message.strip():
            return ToolResult(success=False, output="", error="commit message required")

        cwd = ctx.worktree_path or ctx.workspace_path

        # Stage all changes
        code, _, stderr = _run_git(cwd, "add", "-A")
        if code != 0:
            return ToolResult(success=False, output="", error=f"git add failed: {stderr}")

        # Check if there's anything to commit
        code, stdout, _ = _run_git(cwd, "status", "--porcelain")
        if not stdout.strip():
            return ToolResult(success=True, output="nothing to commit (working tree clean)")

        # Commit
        code, stdout, stderr = _run_git(cwd, "commit", "-m", message)
        if code != 0:
            return ToolResult(success=False, output="", error=f"git commit failed: {stderr}")

        # Get the commit hash
        code, hash_stdout, _ = _run_git(cwd, "rev-parse", "HEAD")
        sha = hash_stdout.strip()[:8] if code == 0 else "unknown"

        return ToolResult(
            success=True,
            output=f"committed: {sha}\n{stdout}",
            data={"sha": sha},
        )


class GitBranchTool(BaseTool):
    name = "git_branch"
    description = (
        "List, create, or switch branches. "
        "action='list' (default): list all branches. "
        "action='create': create a new branch. "
        "action='switch': switch to an existing branch."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "switch"],
                "description": "What to do (default 'list')",
            },
            "name": {
                "type": "string",
                "description": "Branch name (required for create/switch)",
            },
        },
    }
    permission = ToolPermission.MODERATE

    def execute(self, ctx: ToolContext, action: str = "list", name: str = "") -> ToolResult:
        cwd = ctx.worktree_path or ctx.workspace_path

        if action == "list":
            code, stdout, stderr = _run_git(cwd, "branch", "-a")
            if code != 0:
                return ToolResult(success=False, output="", error=stderr)
            return ToolResult(success=True, output=stdout or "(no branches)")

        if not name:
            return ToolResult(success=False, output="", error="branch name required")

        if action == "create":
            code, stdout, stderr = _run_git(cwd, "checkout", "-b", name)
            if code != 0:
                return ToolResult(success=False, output="", error=stderr)
            return ToolResult(success=True, output=f"created and switched to branch: {name}")

        if action == "switch":
            code, stdout, stderr = _run_git(cwd, "checkout", name)
            if code != 0:
                return ToolResult(success=False, output="", error=stderr)
            return ToolResult(success=True, output=f"switched to branch: {name}")

        return ToolResult(success=False, output="", error=f"unknown action: {action}")
