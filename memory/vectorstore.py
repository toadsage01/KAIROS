"""
VectorStore — ChromaDB embedded.

Stores file chunks + summaries. Persistent on disk at <repo>/.chroma/.
Zero server setup. The retriever queries this for top-k relevant file
chunks given a task description.

If chromadb isn't installed, all methods degrade gracefully to no-ops
so the coder still runs (just without semantic retrieval — the codemap
still provides structural context).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

try:
    import chromadb  # type: ignore
    _HAS_CHROMA = True
except ImportError:
    chromadb = None  # type: ignore
    _HAS_CHROMA = False


def _chunk_text(text: str, max_chars: int = 1500, overlap: int = 200) -> list[str]:
    """Sliding-window chunker. Returns overlapping text chunks."""
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    i = 0
    while i < len(text):
        out.append(text[i : i + max_chars])
        if i + max_chars >= len(text):
            break
        i += max_chars - overlap
    return out


def _stable_id(path: str, chunk_idx: int) -> str:
    h = hashlib.sha256(f"{path}::{chunk_idx}".encode()).hexdigest()[:16]
    return f"{path}::{h}"


class VectorStore:
    """ChromaDB embedded. Two collections: 'chunks' and 'summaries'."""

    def __init__(self, path: str = "./.chroma"):
        self.path = Path(path).resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._chunks = None
        self._summaries = None
        if _HAS_CHROMA:
            self._client = chromadb.PersistentClient(path=str(self.path))  # type: ignore[union-attr]
            self._chunks = self._client.get_or_create_collection("chunks")  # type: ignore[union-attr]
            self._summaries = self._client.get_or_create_collection("summaries")  # type: ignore[union-attr]

    @property
    def available(self) -> bool:
        return _HAS_CHROMA and self._chunks is not None

    def index_file(self, path: str, content: str) -> int:
        """Chunk + index a file's content. Returns # chunks stored."""
        if not self.available or self._chunks is None:
            return 0
        # First, delete any existing chunks for this path
        try:
            self._chunks.delete(where={"path": path})
        except Exception:
            pass
        chunks = _chunk_text(content)
        ids, docs, metas = [], [], []
        for i, c in enumerate(chunks):
            ids.append(_stable_id(path, i))
            docs.append(c)
            metas.append({"path": path, "chunk_idx": i, "n_chunks": len(chunks)})
        if ids:
            self._chunks.add(ids=ids, documents=docs, metadatas=metas)  # type: ignore[union-attr]
        return len(chunks)

    def index_summary(self, path: str, summary: str) -> None:
        if not self.available or self._summaries is None:
            return
        try:
            self._summaries.delete(where={"path": path})
        except Exception:
            pass
        self._summaries.add(
            ids=[f"summary::{path}"],
            documents=[summary],
            metadatas=[{"path": path}],
        )  # type: ignore[union-attr]

    def query(self, text: str, k: int = 5) -> list[dict[str, Any]]:
        """Top-k chunks by semantic similarity. Returns list of {path, content}."""
        if not self.available or self._chunks is None:
            return []
        try:
            r = self._chunks.query(query_texts=[text], n_results=k)  # type: ignore[union-attr]
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        if not r or not r.get("documents"):
            return out
        docs = r["documents"][0]
        metas = r.get("metadatas", [[]])[0]
        for doc, meta in zip(docs, metas):
            out.append({
                "path": meta.get("path", "?"),
                "content": doc,
            })
        return out

    def stats(self) -> dict[str, int]:
        if not self.available:
            return {"available": 0}
        return {
            "available": 1,
            "chunks": self._chunks.count() if self._chunks else 0,  # type: ignore[union-attr]
            "summaries": self._summaries.count() if self._summaries else 0,  # type: ignore[union-attr]
        }
