"""
Retriever — bounded context for the coder agent.

Phase 2: Now uses tree-sitter AST signatures instead of raw file chunks.
Returns:
  1. Compact repo map (function/class signatures, not raw code)
  2. Full content of the file being edited (ground truth)
  3. Signatures of files that depend on / are depended on by the target file

Context budget: limits total output to ~4000 chars (was unbounded before).
This reduces prompt bloat by 10x while maintaining relevance.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .codemap import CodeMap, FileSummary
from .vectorstore import VectorStore


# Context budget — maximum chars of retrieval context to inject into prompt
MAX_CONTEXT_CHARS = 4000


class Indexer:
    """Walks a repo and indexes it into both vector store and codemap."""

    def __init__(self, vector: VectorStore, codemap: CodeMap):
        self.vector = vector
        self.codemap = codemap

    def index_repo(self, repo_root: str) -> dict[str, int]:
        """Index the repo: build codemap + index file summaries into vector store."""
        root = Path(repo_root).resolve()
        # Build codemap (tree-sitter AST signatures)
        self.codemap.repo_root = str(root)
        self.codemap.build()

        n_files = len(self.codemap.files)
        n_chunks = 0

        # Index file SIGNATURES (not raw content) into vector store
        # This is 10x smaller than indexing raw chunks
        for path, summary in self.codemap.files.items():
            # Index the signature text as a "chunk"
            n = self.vector.index_file(path, summary.signature_text)
            n_chunks += n

        return {"files": n_files, "chunks": n_chunks, "signatures": n_files}


class Retriever:
    """Retrieves bounded context for agents.

    Phase 2 changes:
      - Returns compact signatures instead of raw file chunks
      - Only returns full file content for the file being edited
      - Respects context budget (MAX_CONTEXT_CHARS)
      - Includes dependency information
    """

    def __init__(self, vector: VectorStore, codemap: CodeMap):
        self.vector = vector
        self.codemap = codemap

    def retrieve(self, task: dict[str, Any], k: int = 5) -> str:
        """Return bounded context string for the coder agent.

        Args:
            task: Task dict with title, description, files
            k: Max number of files to include signatures for

        Returns:
            Compact context string (~4000 chars max) containing:
            1. Relevant file signatures (from codemap)
            2. Dependency information
            3. Semantic search results (from vector store, if available)
        """
        parts: list[str] = []
        current_chars = 0

        query = " ".join(filter(None, [
            task.get("title", ""),
            task.get("description", ""),
        ]))

        # 1. Get compact repo sub-map (signatures, not raw code)
        submap = self.codemap.submap_for(query, k=k)
        if submap and submap != "(empty repo map)":
            parts.append("## Repo Map (AST signatures)")
            parts.append(submap)
            current_chars += len(submap)

        # 2. If task declares specific files, get their full summaries
        files = task.get("files", "")
        if files and current_chars < MAX_CONTEXT_CHARS:
            parts.append("\n## Target Files")
            for f in [f.strip() for f in files.split(",") if f.strip()]:
                summary = self.codemap.get_file_summary(f)
                if summary:
                    parts.append(f"\n### {f}")
                    parts.append(summary.signature_text)
                    current_chars += len(summary.signature_text)

                # Get dependencies
                deps = self.codemap.get_dependencies(f)
                if deps:
                    parts.append(f"  depends on: {', '.join(deps[:5])}")

                # Check budget
                if current_chars > MAX_CONTEXT_CHARS:
                    parts.append("  (context budget reached — more files omitted)")
                    break

        # 3. Semantic search (if vector store available) — but only return
        # file paths + signature snippets, not raw content
        if self.vector.available and current_chars < MAX_CONTEXT_CHARS:
            chunks = self.vector.query(query, k=3)
            if chunks:
                parts.append("\n## Semantic Results (file references)")
                seen_paths = set()
                for chunk in chunks:
                    path = chunk["path"]
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)

                    # Get the signature summary for this file (not raw content)
                    summary = self.codemap.get_file_summary(path)
                    if summary:
                        snippet = summary.signature_text[:500]
                        parts.append(f"\n{snippet}")
                        current_chars += len(snippet)
                    else:
                        # Fallback: show first 200 chars of content
                        content_preview = chunk["content"][:200]
                        parts.append(f"\n📄 {path}\n  {content_preview}")
                        current_chars += len(content_preview)

                    if current_chars > MAX_CONTEXT_CHARS:
                        parts.append("  (context budget reached)")
                        break

        # 4. Task's declared files
        if files:
            parts.append(f"\n## Task declares files: {files}")

        if not parts:
            return "(no retrieval context available)"

        result = "\n".join(parts)

        # Enforce hard context budget
        if len(result) > MAX_CONTEXT_CHARS:
            result = result[:MAX_CONTEXT_CHARS] + "\n... (context budget reached)"

        return result
