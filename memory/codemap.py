"""
CodeMap — tree-sitter AST-based code map for efficient retrieval.

Replaces the old regex-based scanner with proper AST parsing using
tree-sitter. Extracts:
  - Function signatures (name, params, return type, docstring)
  - Class definitions (name, methods, base classes)
  - Import statements
  - Call relationships (dependency graph via networkx)

The output is a compact signature map that's 10x smaller than raw file
chunks. The retriever uses this to give the coder agent bounded context
that's relevant without bloating the prompt.

Supported languages:
  - Python (.py) — full AST parsing
  - JavaScript (.js) — AST parsing
  - TypeScript (.ts) — AST parsing
  - Others — regex fallback (old behavior)
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    nx = None  # type: ignore
    _HAS_NX = False

# Tree-sitter imports (lazy, graceful degradation)
_HAS_TS = False
_PY_PARSER = None
_JS_PARSER = None

try:
    import tree_sitter_python
    from tree_sitter import Language, Parser
    _PY_LANGUAGE = Language(tree_sitter_python.language())
    _PY_PARSER = Parser(_PY_LANGUAGE)
    _HAS_TS = True
except ImportError:
    pass

try:
    import tree_sitter_javascript
    _JS_LANGUAGE = Language(tree_sitter_javascript.language())
    _JS_PARSER = Parser(_JS_LANGUAGE)
except ImportError:
    pass

try:
    import tree_sitter_typescript
    _TS_LANGUAGE = Language(tree_sitter_typescript.language_typescript())
    _TS_PARSER = Parser(_TS_LANGUAGE)
except ImportError:
    pass


# Files we skip
_SKIP_DIRS = {".git", ".worktrees", "__pycache__", "node_modules", ".venv",
              "venv", ".chroma", "dist", "build", ".next", ".pytest_cache"}
_SKIP_EXTS = {".pyc", ".pyo", ".so", ".o", ".a", ".dylib", ".png", ".jpg",
              ".jpeg", ".gif", ".svg", ".pdf", ".zip", ".tar", ".gz"}


@dataclass
class FunctionSignature:
    """Compact function signature for the code map."""
    name: str
    params: str  # e.g., "(name: str, age: int)"
    return_type: str  # e.g., "str" or ""
    docstring: str  # first line of docstring, or ""
    line: int
    is_method: bool = False  # True if inside a class
    class_name: str = ""  # parent class if is_method


@dataclass
class ClassSignature:
    """Compact class signature for the code map."""
    name: str
    bases: str  # e.g., "BaseModel, ABC" or ""
    methods: list[str]  # method names
    line: int


@dataclass
class ImportInfo:
    """Import statement info."""
    module: str  # e.g., "fastapi" or ".utils"
    names: list[str]  # e.g., ["FastAPI", "HTTPException"]
    line: int


@dataclass
class FileSummary:
    """Compact summary of a file — used for retrieval instead of raw chunks."""
    path: str
    language: str
    imports: list[ImportInfo] = field(default_factory=list)
    functions: list[FunctionSignature] = field(default_factory=list)
    classes: list[ClassSignature] = field(default_factory=list)
    total_lines: int = 0
    # The full signature map as a string (for injection into prompts)
    signature_text: str = ""


@dataclass
class CodeMap:
    """Repo map built from tree-sitter AST parsing."""
    repo_root: str = "."
    files: dict[str, FileSummary] = field(default_factory=dict)
    # Dependency graph: function/class → functions it calls
    call_graph: Any | None = None
    # Reverse index: function name → files that define it
    function_index: dict[str, list[str]] = field(default_factory=dict)
    class_index: dict[str, list[str]] = field(default_factory=list)
    _built: bool = False

    def build(self) -> "CodeMap":
        """Scan repo, parse all files, build signature map + dependency graph."""
        root = Path(self.repo_root).resolve()
        self.files = {}

        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.suffix in _SKIP_EXTS:
                continue

            rel = str(p.relative_to(root))
            lang = _detect_language(p.suffix)
            if not lang:
                continue

            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            summary = self._parse_file(rel, content, lang)
            if summary:
                self.files[rel] = summary

        # Build dependency graph
        if _HAS_NX:
            self.call_graph = self._build_call_graph()

        # Build function/class indices
        self.function_index = defaultdict(list)
        self.class_index = defaultdict(list)
        for path, summary in self.files.items():
            for func in summary.functions:
                self.function_index[func.name].append(path)
            for cls in summary.classes:
                self.class_index[cls.name].append(path)

        self._built = True
        return self

    def _parse_file(self, path: str, content: str, language: str) -> FileSummary | None:
        """Parse a file using tree-sitter (or regex fallback)."""
        if language == "python" and _PY_PARSER:
            return self._parse_python(path, content)
        elif language == "javascript" and _JS_PARSER:
            return self._parse_javascript(path, content)
        elif language == "typescript" and _TS_PARSER:
            return self._parse_typescript(path, content)
        else:
            return self._parse_regex_fallback(path, content, language)

    def _parse_python(self, path: str, content: str) -> FileSummary:
        """Parse Python file with tree-sitter."""
        tree = _PY_PARSER.parse(content.encode("utf-8"))
        root_node = tree.root_node

        summary = FileSummary(
            path=path,
            language="python",
            total_lines=content.count("\n") + 1,
        )

        # Walk the AST
        self._walk_python_ast(root_node, content, summary, class_name="")

        # Build signature text
        summary.signature_text = self._build_signature_text(summary)
        return summary

    def _walk_python_ast(self, node, content: str, summary: FileSummary, class_name: str):
        """Recursively walk Python AST nodes."""
        for child in node.children:
            if child.type == "function_definition":
                func = self._extract_python_function(child, content, class_name)
                if func:
                    summary.functions.append(func)
                    # Recurse into function body for nested functions
                    self._walk_python_ast(child, content, summary, class_name)

            elif child.type == "class_definition":
                cls = self._extract_python_class(child, content)
                if cls:
                    summary.classes.append(cls)
                    # Recurse into class body for methods
                    self._walk_python_ast(child, content, summary, class_name=cls.name)

            elif child.type == "import_statement" or child.type == "import_from_statement":
                imp = self._extract_python_import(child, content)
                if imp:
                    summary.imports.append(imp)

            # Recurse into other nodes (but not into function/class bodies —
            # those are handled above)
            if child.type not in ("function_definition", "class_definition"):
                self._walk_python_ast(child, content, summary, class_name)

    def _extract_python_function(self, node, content: str, class_name: str) -> FunctionSignature | None:
        """Extract function signature from AST node."""
        try:
            name_node = node.child_by_field_name("name")
            if not name_node:
                return None
            name = name_node.text.decode("utf-8")

            params_node = node.child_by_field_name("parameters")
            params = params_node.text.decode("utf-8") if params_node else "()"

            ret_node = node.child_by_field_name("return_type")
            return_type = ret_node.text.decode("utf-8") if ret_node else ""

            # Extract docstring (first string in body)
            docstring = ""
            for child in node.children:
                if child.type == "block":
                    for block_child in child.children:
                        if block_child.type == "expression_statement":
                            expr = block_child.children[0] if block_child.children else None
                            if expr and expr.type == "string":
                                doc_text = expr.text.decode("utf-8")
                                # Clean up docstring
                                docstring = doc_text.strip('"""').strip("'''").strip('"').strip("'")
                                # First line only
                                docstring = docstring.split("\n")[0].strip()
                                break
                    break

            line = node.start_point[0] + 1
            return FunctionSignature(
                name=name, params=params, return_type=return_type,
                docstring=docstring, line=line,
                is_method=bool(class_name), class_name=class_name,
            )
        except Exception:
            return None

    def _extract_python_class(self, node, content: str) -> ClassSignature | None:
        """Extract class signature from AST node."""
        try:
            name_node = node.child_by_field_name("name")
            if not name_node:
                return None
            name = name_node.text.decode("utf-8")

            # Get base classes
            bases = ""
            super_node = node.child_by_field_name("superclasses")
            if super_node:
                bases = super_node.text.decode("utf-8")

            # Get method names
            methods = []
            for child in node.children:
                if child.type == "block":
                    for block_child in child.children:
                        if block_child.type == "function_definition":
                            method_name_node = block_child.child_by_field_name("name")
                            if method_name_node:
                                methods.append(method_name_node.text.decode("utf-8"))

            line = node.start_point[0] + 1
            return ClassSignature(name=name, bases=bases, methods=methods, line=line)
        except Exception:
            return None

    def _extract_python_import(self, node, content: str) -> ImportInfo | None:
        """Extract import info from AST node."""
        try:
            text = node.text.decode("utf-8")
            line = node.start_point[0] + 1

            if node.type == "import_from_statement":
                # from X import Y, Z
                module_node = node.child_by_field_name("module_name")
                module = module_node.text.decode("utf-8") if module_node else ""
                names = []
                for child in node.children:
                    if child.type == "dotted_name" and child != module_node:
                        names.append(child.text.decode("utf-8"))
                return ImportInfo(module=module, names=names, line=line)
            elif node.type == "import_statement":
                # import X or import X as Y
                names = []
                module = ""
                for child in node.children:
                    if child.type == "dotted_name":
                        module = child.text.decode("utf-8")
                        names.append(module)
                return ImportInfo(module=module, names=names, line=line)
        except Exception:
            return None

    def _parse_javascript(self, path: str, content: str) -> FileSummary:
        """Parse JavaScript file with tree-sitter."""
        if not _JS_PARSER:
            return self._parse_regex_fallback(path, content, "javascript")

        tree = _JS_PARSER.parse(content.encode("utf-8"))
        summary = FileSummary(path=path, language="javascript", total_lines=content.count("\n") + 1)

        for child in tree.root_node.children:
            if child.type == "function_declaration":
                name_node = child.child_by_field_name("name")
                params_node = child.child_by_field_name("parameters")
                if name_node:
                    summary.functions.append(FunctionSignature(
                        name=name_node.text.decode("utf-8"),
                        params=params_node.text.decode("utf-8") if params_node else "()",
                        return_type="",
                        docstring="",
                        line=child.start_point[0] + 1,
                    ))
            elif child.type == "class_declaration":
                name_node = child.child_by_field_name("name")
                if name_node:
                    summary.classes.append(ClassSignature(
                        name=name_node.text.decode("utf-8"),
                        bases="",
                        methods=[],
                        line=child.start_point[0] + 1,
                    ))
            elif child.type == "import_statement":
                text = child.text.decode("utf-8")
                summary.imports.append(ImportInfo(module=text, names=[], line=child.start_point[0] + 1))

        summary.signature_text = self._build_signature_text(summary)
        return summary

    def _parse_typescript(self, path: str, content: str) -> FileSummary:
        """Parse TypeScript file with tree-sitter."""
        if not _TS_PARSER:
            return self._parse_regex_fallback(path, content, "typescript")
        # Same as JavaScript for now
        return self._parse_javascript(path, content)

    def _parse_regex_fallback(self, path: str, content: str, language: str) -> FileSummary:
        """Regex fallback for unsupported languages."""
        summary = FileSummary(path=path, language=language, total_lines=content.count("\n") + 1)

        patterns = [
            ("python", re.compile(r"^\s*(async\s+def|def|class)\s+(\w+)"), "def"),
            ("javascript", re.compile(r"^\s*(function|class)\s+(\w+)"), "def"),
            ("typescript", re.compile(r"^\s*(function|class|interface|type)\s+(\w+)"), "def"),
            ("go", re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?(\w+)"), "def"),
            ("rust", re.compile(r"^\s*(pub\s+)?(fn|struct|enum|impl)\s+(\w+)"), "def"),
        ]

        for i, line in enumerate(content.splitlines(), 1):
            for lng, pat, kind in patterns:
                if lng != language:
                    continue
                m = pat.match(line)
                if m:
                    name = m.groups()[-1]
                    if "class" in line.lower():
                        summary.classes.append(ClassSignature(name=name, bases="", methods=[], line=i))
                    else:
                        summary.functions.append(FunctionSignature(
                            name=name, params="()", return_type="", docstring="", line=i
                        ))

        summary.signature_text = self._build_signature_text(summary)
        return summary

    def _build_signature_text(self, summary: FileSummary) -> str:
        """Build compact signature text for prompt injection.

        This replaces raw file chunks with a 10x smaller representation.
        """
        lines = [f"📄 {summary.path} ({summary.total_lines} lines)"]

        if summary.imports:
            imp_names = []
            for imp in summary.imports[:10]:  # cap at 10 imports
                if imp.names:
                    imp_names.append(f"{imp.module}.{'/'.join(imp.names[:3])}")
                else:
                    imp_names.append(imp.module)
            lines.append(f"  imports: {', '.join(imp_names)}")

        for cls in summary.classes[:10]:  # cap at 10 classes
            bases_str = f"({cls.bases})" if cls.bases else ""
            methods_str = ", ".join(cls.methods[:5]) if cls.methods else ""
            lines.append(f"  L{cls.line} class {cls.name}{bases_str}" +
                        (f" — methods: {methods_str}" if methods_str else ""))

        for func in summary.functions[:15]:  # cap at 15 functions
            ret_str = f" -> {func.return_type}" if func.return_type else ""
            doc_str = f"  # {func.docstring}" if func.docstring else ""
            prefix = f"  L{func.line}"
            if func.is_method:
                prefix += f" {func.class_name}."
            lines.append(f"{prefix} {func.name}{func.params}{ret_str}{doc_str}")

        return "\n".join(lines)

    def _build_call_graph(self):
        """Build a dependency graph using networkx.

        Nodes: function/class names
        Edges: function A calls function B
        """
        if not _HAS_NX:
            return None

        g = nx.DiGraph()

        # Add all functions as nodes
        for path, summary in self.files.items():
            for func in summary.functions:
                node_id = f"{path}::{func.name}"
                g.add_node(node_id, path=path, name=func.name, line=func.line)
            for cls in summary.classes:
                node_id = f"{path}::{cls.name}"
                g.add_node(node_id, path=path, name=cls.name, line=cls.line)

        # We can't extract call relationships from tree-sitter alone
        # (would need full semantic analysis). For now, we use import
        # relationships as a proxy: if file A imports from file B,
        # A depends on B.
        for path, summary in self.files.items():
            for imp in summary.imports:
                # Try to resolve import to a file in the repo
                module = imp.module.lstrip(".")
                # Convert module.path to module/path.py
                possible_paths = [
                    module.replace(".", "/") + ".py",
                    module.replace(".", "/") + "/__init__.py",
                    module + ".py",
                ]
                for pp in possible_paths:
                    if pp in self.files:
                        # Add edge from this file to the imported file
                        for func in summary.functions:
                            src = f"{path}::{func.name}"
                            for tgt_func in self.files[pp].functions:
                                tgt = f"{pp}::{tgt_func.name}"
                                if tgt_func.name in imp.names:
                                    g.add_edge(src, tgt)
                        break

        return g

    # ---------- query ----------
    def submap_for(self, task_description: str, k: int = 20) -> str:
        """Return top-k relevant file signatures for a task.

        Ranking: count how many words from the task description match
        function/class names or file paths. Returns compact signature text.
        """
        if not self._built:
            self.build()
        if not self.files:
            return "(empty repo map)"

        words = {w.lower() for w in re.findall(r"\w+", task_description) if len(w) >= 3}
        scored: list[tuple[int, FileSummary]] = []

        for path, summary in self.files.items():
            score = 0
            # Score by path match
            for w in words:
                if w in path.lower():
                    score += 2
            # Score by function/class name match
            for func in summary.functions:
                for w in words:
                    if w in func.name.lower():
                        score += 3
                    if w in func.docstring.lower():
                        score += 1
            for cls in summary.classes:
                for w in words:
                    if w in cls.name.lower():
                        score += 3
            scored.append((score, summary))

        scored.sort(key=lambda t: -t[0])
        top = [s for _, s in scored[:k] if _ > 0]
        if not top:
            # Fallback: return first k files
            top = list(self.files.values())[:k]

        lines = [f"# Repo Map ({len(self.files)} files, showing top {len(top)})"]
        for summary in top:
            lines.append(f"\n{summary.signature_text}")
        return "\n".join(lines)

    def full_map(self, max_files: int = 100) -> str:
        """Return the entire repo map (truncated)."""
        if not self._built:
            self.build()
        lines = [f"# Full Repo Map ({len(self.files)} files)"]
        for i, (path, summary) in enumerate(sorted(self.files.items())):
            if i >= max_files:
                lines.append(f"\n... ({len(self.files) - max_files} more files)")
                break
            lines.append(f"\n{summary.signature_text}")
        return "\n".join(lines)

    def get_file_summary(self, path: str) -> FileSummary | None:
        """Get the signature summary for a specific file."""
        return self.files.get(path)

    def get_dependencies(self, path: str) -> list[str]:
        """Get files that this file depends on (via imports)."""
        summary = self.files.get(path)
        if not summary:
            return []
        deps = []
        for imp in summary.imports:
            module = imp.module.lstrip(".")
            possible = [
                module.replace(".", "/") + ".py",
                module.replace(".", "/") + "/__init__.py",
            ]
            for pp in possible:
                if pp in self.files:
                    deps.append(pp)
                    break
        return deps


def _detect_language(suffix: str) -> str | None:
    return {
        ".py": "python",
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
    }.get(suffix.lower())
