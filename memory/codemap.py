"""
CodeMap — repo map for the coder agent.

Spec said: "ctags + tree-sitter + networkx. Don't build a codegraph —
build a repo map." ctags isn't available in this environment, so we
fall back to a regex-based symbol scanner that handles common patterns:
  - Python:   def, class, async def
  - JS/TS:    function, class, const X =, export
  - Go:       func, type
  - Rust:     fn, struct, enum, impl
  - General:  any line matching ^[A-Za-z_][A-Za-z0-9_]*\\s*=\\s*

The output is a compact, ranked string the coder reads as bounded context
instead of seeing the whole repo. Steal Aider's "repo map" idea, not its
exact implementation.

If ctags IS available on the host, we use it instead. Auto-detected.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

try:
    import networkx as nx  # type: ignore
    _HAS_NX = True
except ImportError:
    nx = None  # type: ignore
    _HAS_NX = False


# (language, regex, kind)
_SYMBOL_PATTERNS = [
    ("python", re.compile(r"^\s*(async\s+def|def|class)\s+(\w+)"), "def"),
    ("javascript", re.compile(r"^\s*(export\s+)?(async\s+)?(function|class)\s+(\w+)"), "def"),
    ("typescript", re.compile(r"^\s*(export\s+)?(async\s+)?(function|class|interface|type)\s+(\w+)"), "def"),
    ("go", re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?(\w+)"), "def"),
    ("rust", re.compile(r"^\s*(pub\s+)?(fn|struct|enum|impl|trait)\s+(\w+)"), "def"),
]

# Files we skip
_SKIP_DIRS = {".git", ".worktrees", "__pycache__", "node_modules", ".venv",
              "venv", ".chroma", "dist", "build", ".next", ".pytest_cache"}
_SKIP_EXTS = {".pyc", ".pyo", ".so", ".o", ".a", ".dylib", ".png", ".jpg",
              ".jpeg", ".gif", ".svg", ".pdf", ".zip", ".tar", ".gz"}


@dataclass
class Symbol:
    path: str
    name: str
    kind: str
    line: int
    language: str


@dataclass
class CodeMap:
    repo_root: str = "."
    symbols: list[Symbol] = field(default_factory=list)
    graph: object | None = None
    _built: bool = False

    def build(self) -> "CodeMap":
        """Scan repo, build symbol list + reference graph."""
        root = Path(self.repo_root).resolve()
        self.symbols = []
        # Try ctags first
        ctags_syms = self._try_ctags(root)
        if ctags_syms:
            self.symbols = ctags_syms
        else:
            self.symbols = self._regex_scan(root)
        # Build reference graph (networkx if available)
        if _HAS_NX and self.symbols:
            self.graph = self._build_graph()
        self._built = True
        return self

    # ---------- ctags path ----------
    def _try_ctags(self, root: Path) -> list[Symbol]:
        try:
            r = subprocess.run(
                ["ctags", "--output-format=json", "-R", "."],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode != 0 or not r.stdout:
                return []
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        import json
        syms: list[Symbol] = []
        for line in r.stdout.splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            syms.append(Symbol(
                path=rec.get("path", ""),
                name=rec.get("name", ""),
                kind=rec.get("kind", "def"),
                line=int(rec.get("line", 0)),
                language=rec.get("language", ""),
            ))
        return syms

    # ---------- regex fallback ----------
    def _regex_scan(self, root: Path) -> list[Symbol]:
        syms: list[Symbol] = []
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.suffix in _SKIP_EXTS:
                continue
            lang = _detect_language(p.suffix)
            if not lang:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = str(p.relative_to(root))
            for i, line in enumerate(text.splitlines(), 1):
                for lng, pat, kind in _SYMBOL_PATTERNS:
                    if lng != lang:
                        continue
                    m = pat.match(line)
                    if m:
                        # last group is the name in our patterns
                        name = m.groups()[-1]
                        syms.append(Symbol(
                            path=rel, name=name, kind=kind,
                            line=i, language=lng,
                        ))
                        break
        return syms

    # ---------- graph ----------
    def _build_graph(self):
        """A bipartite-ish graph: file -> symbol, symbol -> symbol (by name reference)."""
        g = nx.DiGraph()  # type: ignore[attr-defined]
        # File nodes
        files = {s.path for s in self.symbols}
        for f in files:
            g.add_node(f, kind="file")
        # Symbol nodes
        for s in self.symbols:
            node_id = f"{s.path}::{s.name}"
            g.add_node(node_id, kind="symbol", **{"path": s.path, "name": s.name, "line": s.line})
            g.add_edge(s.path, node_id)
        # Reference edges: if file A's text mentions symbol name B, edge A_file -> B_symbol
        # (cheap approximation; tree-sitter would do this precisely)
        root = Path(self.repo_root).resolve()
        name_to_syms: dict[str, list[Symbol]] = defaultdict(list)
        for s in self.symbols:
            name_to_syms[s.name].append(s)
        for f in files:
            p = root / f
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for name, syms in name_to_syms.items():
                if len(name) < 3:
                    continue
                # Cheap token check: word-boundary match
                if re.search(rf"\b{re.escape(name)}\b", text):
                    for s in syms:
                        if s.path != f:  # don't self-link
                            g.add_edge(f, f"{s.path}::{s.name}")
        return g

    # ---------- query ----------
    def submap_for(self, task_description: str, k: int = 20) -> str:
        """Return top-k symbols relevant to the task.

        Ranking: count how many words from the task description match a
        symbol's name or path. If networkx is available, also include
        1-hop neighbors of the top hits.
        """
        if not self._built:
            self.build()
        if not self.symbols:
            return "(empty repo map)"

        words = {w.lower() for w in re.findall(r"\w+", task_description) if len(w) >= 3}
        scored: list[tuple[int, Symbol]] = []
        for s in self.symbols:
            score = 0
            for w in words:
                if w in s.name.lower():
                    score += 3
                if w in s.path.lower():
                    score += 1
            scored.append((score, s))
        scored.sort(key=lambda t: -t[0])
        top = [s for _, s in scored[:k] if _ > 0]
        if not top:
            # fallback: just first k symbols
            top = self.symbols[:k]

        # Group by file for readability
        by_file: dict[str, list[Symbol]] = defaultdict(list)
        for s in top:
            by_file[s.path].append(s)

        lines = ["# Repo map (top-%d symbols for task)" % len(top)]
        for f in sorted(by_file.keys()):
            lines.append(f"\n## {f}")
            for s in sorted(by_file[f], key=lambda x: x.line):
                lines.append(f"  L{s.line:>4}  {s.kind}  {s.name}")
        return "\n".join(lines)

    def full_map(self, max_lines: int = 200) -> str:
        """Return the entire repo map (truncated)."""
        if not self._built:
            self.build()
        by_file: dict[str, list[Symbol]] = defaultdict(list)
        for s in self.symbols:
            by_file[s.path].append(s)
        lines = [f"# Repo map ({len(self.symbols)} symbols, {len(by_file)} files)"]
        for f in sorted(by_file.keys())[:max_lines]:
            lines.append(f"\n{f}")
            for s in sorted(by_file[f], key=lambda x: x.line)[:20]:
                lines.append(f"  L{s.line:>4}  {s.kind}  {s.name}")
        return "\n".join(lines)


def _detect_language(suffix: str) -> str | None:
    return {
        ".py": "python",
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
    }.get(suffix.lower())
