"""
FileState — the blackboard. The ONLY way agents communicate.

Every agent reads from state/*.md and writes to state/*.md. No agent ever
talks to another agent directly. This is what keeps token cost predictable
and makes the system debuggable by `cat` instead of by log scraper.

All paths are relative to the project state_dir (default ./state).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class FileState:
    def __init__(self, state_dir: str | Path = "./state"):
        self.root = Path(state_dir).resolve()
        for sub in ("", "research", "changes", "review", "hitl"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # ---------- markdown helpers ----------
    def write_md(self, name: str, content: str, subdir: str = "") -> Path:
        """Write a markdown file. name may include .md or not."""
        if not name.endswith(".md"):
            name = name + ".md"
        path = self.root / subdir / name if subdir else self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_md(self, name: str, subdir: str = "") -> str | None:
        if not name.endswith(".md"):
            name = name + ".md"
        path = self.root / subdir / name if subdir else self.root / name
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    # ---------- json helpers (for tasks.json, hitl signals) ----------
    def write_json(self, name: str, data: Any, subdir: str = "") -> Path:
        if not name.endswith(".json"):
            name = name + ".json"
        path = self.root / subdir / name if subdir else self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def read_json(self, name: str, subdir: str = "") -> Any | None:
        if not name.endswith(".json"):
            name = name + ".json"
        path = self.root / subdir / name if subdir else self.root / name
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ---------- domain-specific helpers ----------
    def set_goal(self, goal: str) -> Path:
        """goal.md is the immutable north star. Writing it initializes a run."""
        return self.write_md(
            "goal",
            f"# Goal\n\n{goal}\n\n_Set at {_ts()}_\n",
        )

    def get_goal(self) -> str | None:
        return self.read_md("goal")

    def append_log(self, line: str) -> None:
        """Append-only log. UI tails this file."""
        log_path = self.root.parent / "logs" / "orchestrator.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{_ts()}] {line}\n")

    def read_log(self, tail: int = 200) -> str:
        log_path = self.root.parent / "logs" / "orchestrator.log"
        if not log_path.exists():
            return ""
        lines = log_path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-tail:])

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the whole state for the UI/API."""
        snap: dict[str, Any] = {}
        for sub in ("", "research", "changes", "review", "hitl"):
            d = self.root / sub if sub else self.root
            files = sorted(p.name for p in d.glob("*") if p.is_file())
            key = sub or "root"
            snap[key] = {}
            for fname in files:
                p = d / fname
                if fname.endswith(".json"):
                    snap[key][fname] = self.read_json(fname, sub)
                else:
                    txt = p.read_text(encoding="utf-8")
                    snap[key][fname] = txt[:4000]  # truncate for UI
        snap["log"] = self.read_log()
        return snap
