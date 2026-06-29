"""
Retriever — bounded context for the coder agent.

Given a task, returns a compact string with:
  1. Top-k relevant file chunks from the vector store (semantic)
  2. A ranked repo sub-map (structural)

The coder reads THIS instead of the whole repo. Token cost stays low
even for large repos.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .codemap import CodeMap
from .vectorstore import VectorStore


class Indexer:
    """Walks a repo and indexes it into both vector store and codemap."""

    def __init__(self, vector: VectorStore, codemap: CodeMap):
        self.vector = vector
        self.codemap = codemap

    def index_repo(self, repo_root: str) -> dict[str, int]:
        root = Path(repo_root).resolve()
        n_files = 0
        n_chunks = 0
        # Build codemap (which scans files anyway) — symbols live on codemap.symbols
        self.codemap.repo_root = str(root)
        self.codemap.build()
        # Walk files for content indexing into the vector store
        skip_dirs = {".git", ".worktrees", "__pycache__", "node_modules",
                     ".venv", "venv", ".chroma", "dist", "build"}
        skip_exts = {".pyc", ".pyo", ".so", ".png", ".jpg", ".jpeg", ".gif",
                     ".svg", ".pdf", ".zip", ".tar", ".gz"}
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in skip_dirs for part in p.parts):
                continue
            if p.suffix in skip_exts:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = str(p.relative_to(root))
            n = self.vector.index_file(rel, content)
            n_chunks += n
            n_files += 1
        return {"files": n_files, "chunks": n_chunks}


class Retriever:
    def __init__(self, vector: VectorStore, codemap: CodeMap):
        self.vector = vector
        self.codemap = codemap

    def retrieve(self, task: dict[str, Any], k: int = 5) -> str:
        """Return a bounded context string for the coder agent."""
        parts: list[str] = []
        # 1. Semantic: top-k chunks
        query = " ".join(filter(None, [
            task.get("title", ""),
            task.get("description", ""),
        ]))
        chunks = self.vector.query(query, k=k) if self.vector.available else []
        if chunks:
            parts.append("## Relevant file chunks (semantic)")
            seen: set[str] = set()
            for c in chunks:
                if c["path"] in seen:
                    continue
                seen.add(c["path"])
                parts.append(f"\n### {c['path']}")
                parts.append("```\n" + c["content"][:1200] + "\n```")
        # 2. Structural: ranked repo sub-map
        submap = self.codemap.submap_for(query, k=20)
        if submap and submap != "(empty repo map)":
            parts.append("\n## Repo map (top-20 symbols for task)")
            parts.append(submap)
        # 3. Task's declared files (if any)
        files = task.get("files", "")
        if files:
            parts.append("\n## Task declares files:")
            parts.append(files)
        if not parts:
            return "(no retrieval context available)"
        return "\n".join(parts)
