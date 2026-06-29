"""Phase 2 — git operations. One worktree per task branch."""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitOps:
    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root).resolve()

    def _run(self, *args: str) -> str:
        r = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            raise RuntimeError(f"git {args}: {r.stderr}")
        return r.stdout.strip()

    def create_worktree(self, branch: str, path: str) -> str:
        """Create a git worktree at `path` on a new branch."""
        return self._run("worktree", "add", "-b", branch, path, "HEAD")

    def remove_worktree(self, path: str) -> str:
        return self._run("worktree", "remove", "--force", path)

    def commit_all(self, message: str) -> str:
        self._run("add", "-A")
        return self._run("commit", "-m", message)

    def merge_branch(self, branch: str) -> str:
        return self._run("merge", "--no-ff", branch, "-m", f"merge {branch}")
