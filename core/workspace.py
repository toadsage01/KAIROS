"""
Workspace — per-task git worktree lifecycle.

For each task, the orchestrator asks the workspace for a `Worktree`:
  1. If <target_repo> isn't a git repo yet, init + initial commit.
  2. Create a worktree at <target_repo>/.worktrees/<task_id>/ on a new
     branch named `myforge/<task_id>`.
  3. Expose `.repo_root` so agents can write/read files there.
  4. On approval, merge `myforge/<task_id>` back into the target repo's
     current branch, then remove the worktree.
  5. On rejection, keep the worktree so the bugfixer can edit it; the
     next coder/bugfixer call reuses it.

Worktrees are how we sandbox tasks without Docker. They're real git
branches — mergeable, diffable, abortable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=check,
    )


class Worktree:
    """A git worktree for one task. Created lazily; reused across coder/bugfixer."""

    def __init__(self, target_repo: str | Path, task_id: str):
        self.target_repo = Path(target_repo).resolve()
        self.task_id = task_id
        self.branch = f"myforge/{task_id}"
        self.path = self.target_repo / ".worktrees" / task_id
        self._ensured = False

    def ensure(self) -> Path:
        """Make sure the worktree exists. Returns the worktree repo root."""
        if self._ensured:
            return self.path
        # Make sure target_repo is a git repo with at least one commit
        self._ensure_target_repo()
        # If worktree already exists (e.g. from a previous bugfixer pass),
        # reuse it. Otherwise create.
        if not self.path.exists():
            # Delete stale branch if it exists (e.g. from a previous run)
            try:
                _run_git(self.target_repo, "branch", "-D", self.branch, check=False)
            except Exception:
                pass
            r = _run_git(
                self.target_repo,
                "worktree", "add", "-b", self.branch,
                str(self.path), "HEAD",
            )
            if r.returncode != 0:
                raise RuntimeError(f"worktree add failed: {r.stderr}")
        self._ensured = True
        return self.path

    def _ensure_target_repo(self) -> None:
        self.target_repo.mkdir(parents=True, exist_ok=True)
        if not (self.target_repo / ".git").exists():
            _run_git(self.target_repo, "init", check=True)
            _run_git(self.target_repo, "config", "user.email", "myforge@example.com", check=False)
            _run_git(self.target_repo, "config", "user.name", "myforge", check=False)
            # Need at least one commit so worktree add works
            readme = self.target_repo / "README.md"
            if not readme.exists():
                readme.write_text(f"# {self.target_repo.name}\n\nmyforge target repo.\n", encoding="utf-8")
            _run_git(self.target_repo, "add", "-A", check=True)
            _run_git(self.target_repo, "commit", "-m", "initial commit", check=True)

    def write_file(self, rel_path: str, content: str) -> Path:
        """Write a file inside the worktree. Creates parent dirs."""
        root = self.ensure()
        cleaned = rel_path.strip().strip("\"'")
        if not cleaned:
            raise ValueError(f"refusing to write invalid path: {rel_path!r}")
        rel = Path(cleaned)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"refusing to write unsafe path: {rel_path!r}")
        target = root / rel
        resolved = target.resolve()
        if root.resolve() not in resolved.parents and resolved != root.resolve():
            raise ValueError(f"refusing to write outside worktree: {rel_path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if content.rstrip().endswith("\nEOF"):
            content = content.rstrip()[:-4].rstrip() + "\n"
        target.write_text(content, encoding="utf-8")
        return target

    def delete_file(self, rel_path: str) -> Path:
        """Delete a file inside the worktree."""
        root = self.ensure()
        cleaned = rel_path.strip().strip("\"'")
        if not cleaned:
            raise ValueError(f"refusing to delete invalid path: {rel_path!r}")
        rel = Path(cleaned)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"refusing to delete unsafe path: {rel_path!r}")
        target = root / rel
        resolved = target.resolve()
        if root.resolve() not in resolved.parents and resolved != root.resolve():
            raise ValueError(f"refusing to delete outside worktree: {rel_path!r}")
        if target.exists() and not target.is_file():
            raise ValueError(f"refusing to delete non-file path: {rel_path!r}")
        if target.exists():
            target.unlink()
        return target

    def read_file(self, rel_path: str) -> str | None:
        root = self.ensure()
        p = root / rel_path
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    def list_files(self) -> list[str]:
        """Return relative paths of all files in the worktree (excluding .git)."""
        root = self.ensure()
        out: list[str] = []
        for p in root.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
                out.append(str(p.relative_to(root)))
        return sorted(out)

    def commit(self, message: str) -> str:
        """Stage + commit all changes in the worktree. Returns the commit sha."""
        root = self.ensure()
        _run_git(root, "add", "-A", check=True)
        # Check if there's anything to commit
        status = _run_git(root, "status", "--porcelain", check=True)
        if not status.stdout.strip():
            # nothing to commit; return HEAD
            r = _run_git(root, "rev-parse", "HEAD", check=True)
            return r.stdout.strip()
        r = _run_git(root, "commit", "-m", message, check=True)
        return _run_git(root, "rev-parse", "HEAD", check=True).stdout.strip()

    def diff(self, base: str = "HEAD") -> str:
        """Return `git diff` of uncommitted changes."""
        root = self.ensure()
        r = _run_git(root, "diff", base, check=False)
        return r.stdout

    def merge_to_target(self) -> str:
        """Merge this worktree's branch into the target repo's current branch.

        Removes the worktree afterward. Returns the merge commit sha.
        """
        root = self.ensure()
        # Commit any pending changes first
        self.commit(f"myforge: finalize task {self.task_id}")
        # Switch to target repo and merge
        r = _run_git(
            self.target_repo,
            "merge", "--no-ff", self.branch, "-m",
            f"myforge: merge task {self.task_id}",
            check=True,
        )
        # Cleanup: remove worktree + delete branch
        _run_git(self.target_repo, "worktree", "remove", "--force", str(self.path), check=False)
        _run_git(self.target_repo, "branch", "-D", self.branch, check=False)
        self._ensured = False
        return _run_git(self.target_repo, "rev-parse", "HEAD", check=True).stdout.strip()

    def abort(self) -> None:
        """Discard this worktree entirely (no merge)."""
        if self.path.exists():
            _run_git(self.target_repo, "worktree", "remove", "--force", str(self.path), check=False)
        _run_git(self.target_repo, "branch", "-D", self.branch, check=False)
        self._ensured = False


class WorkspaceManager:
    """Owns the worktree lifecycle for the orchestrator."""

    def __init__(self, target_repo: str | Path):
        self.target_repo = Path(target_repo).resolve()

    def for_task(self, task_id: str) -> Worktree:
        return Worktree(self.target_repo, task_id)
