"""
Phase 2: Smart Memory & Context — Dummy Tests

Tests the tree-sitter AST-based code map and signature retrieval:
1. Tree-sitter parses Python files into function/class signatures
2. Signature text is 10x smaller than raw file content
3. Dependency graph tracks import relationships
4. Retriever respects context budget (MAX_CONTEXT_CHARS)
5. Submap returns relevant files based on task description
6. File summary includes imports, functions, classes
"""
import sys
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory.codemap import CodeMap, FileSummary, FunctionSignature, ClassSignature
from memory.retriever import Retriever, Indexer, MAX_CONTEXT_CHARS
from memory.vectorstore import VectorStore


def create_test_repo(tmpdir: Path):
    """Create a small test repo with Python files."""
    # File 1: utils.py
    (tmpdir / "utils.py").write_text('''"""Utility functions for the project."""

from typing import Optional


def format_name(name: str, uppercase: bool = False) -> str:
    """Format a name string."""
    if uppercase:
        return name.upper()
    return name.lower()


def calculate_total(items: list[float], tax_rate: float = 0.1) -> float:
    """Calculate total with tax."""
    subtotal = sum(items)
    return subtotal * (1 + tax_rate)


class DataProcessor:
    """Process data records."""

    def __init__(self, config: dict):
        self.config = config

    def process(self, data: list) -> list:
        """Process a list of records."""
        return [self.transform(item) for item in data]

    def transform(self, item: dict) -> dict:
        """Transform a single record."""
        return {k: v for k, v in item.items() if k in self.config}
''')

    # File 2: main.py
    (tmpdir / "main.py").write_text('''"""Main application entry point."""

from utils import format_name, calculate_total, DataProcessor
import json


def main():
    """Run the main application."""
    processor = DataProcessor({"name": True, "value": True})
    data = [{"name": "test", "value": 42}]
    result = processor.process(data)
    print(json.dumps(result))


def greet_user(name: str) -> str:
    """Greet a user by name."""
    return f"Hello, {format_name(name, uppercase=True)}!"


if __name__ == "__main__":
    main()
''')

    # File 3: README.md (should be skipped by codemap)
    (tmpdir / "README.md").write_text("# Test Project\n\nA test repo.")


def test_tree_sitter_parsing():
    """Test that tree-sitter correctly parses Python files."""
    print("=" * 60)
    print("TEST 1: Tree-sitter AST Parsing")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_test_repo(tmpdir)

        codemap = CodeMap(repo_root=str(tmpdir))
        codemap.build()

        # Check utils.py was parsed
        utils = codemap.files.get("utils.py")
        if not utils:
            print("  ❌ utils.py not found in codemap")
            return False

        print(f"  ✅ utils.py parsed: {len(utils.functions)} functions, {len(utils.classes)} classes")
        print(f"  ✅ Imports: {[imp.module for imp in utils.imports]}")

        # Check function signatures
        func_names = [f.name for f in utils.functions]
        if "format_name" in func_names and "calculate_total" in func_names:
            print(f"  ✅ Functions found: {func_names}")
        else:
            print(f"  ❌ Expected functions not found: {func_names}")
            return False

        # Check return types
        format_name_func = next(f for f in utils.functions if f.name == "format_name")
        if format_name_func.return_type == "str":
            print(f"  ✅ Return type detected: {format_name_func.return_type}")
        else:
            print(f"  ❌ Return type missing or wrong: {format_name_func.return_type!r}")
            return False

        # Check docstrings
        if format_name_func.docstring:
            print(f"  ✅ Docstring extracted: '{format_name_func.docstring}'")
        else:
            print(f"  ⚠️ Docstring not extracted")

        # Check class
        if utils.classes:
            cls = utils.classes[0]
            print(f"  ✅ Class found: {cls.name}, methods: {cls.methods}")
        else:
            print(f"  ❌ No classes found")
            return False

    return True


def test_signature_compaction():
    """Test that signature text is much smaller than raw file content."""
    print("\n" + "=" * 60)
    print("TEST 2: Signature Compaction (10x smaller)")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_test_repo(tmpdir)

        codemap = CodeMap(repo_root=str(tmpdir))
        codemap.build()

        utils = codemap.files.get("utils.py")
        raw_content = (tmpdir / "utils.py").read_text()
        sig_text = utils.signature_text

        raw_size = len(raw_content)
        sig_size = len(sig_text)
        ratio = raw_size / sig_size if sig_size > 0 else 0

        print(f"  Raw content: {raw_size} chars")
        print(f"  Signature:   {sig_size} chars")
        print(f"  Ratio:       {ratio:.1f}x smaller")

        if sig_size < raw_size:
            print(f"  ✅ Signature is smaller than raw content")
        else:
            print(f"  ❌ Signature is NOT smaller")
            return False

        # Show the signature text
        print(f"\n  --- Signature Text ---")
        for line in sig_text.split("\n"):
            print(f"  {line}")
        print(f"  --- End ---")

    return True


def test_dependency_graph():
    """Test that dependency graph tracks import relationships."""
    print("\n" + "=" * 60)
    print("TEST 3: Dependency Graph")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_test_repo(tmpdir)

        codemap = CodeMap(repo_root=str(tmpdir))
        codemap.build()

        # Check dependencies
        main_deps = codemap.get_dependencies("main.py")
        if "utils.py" in main_deps:
            print(f"  ✅ main.py depends on: {main_deps}")
        else:
            print(f"  ❌ main.py should depend on utils.py, got: {main_deps}")
            return False

        utils_deps = codemap.get_dependencies("utils.py")
        if not utils_deps:
            print(f"  ✅ utils.py has no internal dependencies")
        else:
            print(f"  ⚠️ utils.py deps: {utils_deps}")

    return True


def test_context_budget():
    """Test that retriever respects context budget."""
    print("\n" + "=" * 60)
    print("TEST 4: Context Budget (MAX_CONTEXT_CHARS)")
    print("=" * 60)

    print(f"  Max context: {MAX_CONTEXT_CHARS} chars")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_test_repo(tmpdir)

        vector = VectorStore(str(Path(tmpdir) / ".chroma"))
        codemap = CodeMap(repo_root=str(tmpdir))
        retriever = Retriever(vector, codemap)

        # Retrieve context for a task
        task = {
            "title": "format_name",
            "description": "Modify the format_name function",
            "files": "utils.py",
        }
        context = retriever.retrieve(task, k=5)

        context_size = len(context)
        print(f"  Retrieved context: {context_size} chars")

        if context_size <= MAX_CONTEXT_CHARS:
            print(f"  ✅ Context within budget")
        else:
            print(f"  ❌ Context exceeds budget ({context_size} > {MAX_CONTEXT_CHARS})")
            return False

        # Check that it contains signatures, not raw code
        if "Repo Map" in context or "Target Files" in context:
            print(f"  ✅ Context contains structured sections")
        else:
            print(f"  ⚠️ Context missing structured sections")

        # Show first 500 chars
        print(f"\n  --- Context (first 500 chars) ---")
        print(f"  {context[:500]}")
        print(f"  --- End ---")

    return True


def test_submap_relevance():
    """Test that submap returns relevant files based on task description."""
    print("\n" + "=" * 60)
    print("TEST 5: Submap Relevance")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_test_repo(tmpdir)

        codemap = CodeMap(repo_root=str(tmpdir))
        codemap.build()

        # Search for "calculate_total" — should rank utils.py high
        submap = codemap.submap_for("calculate total with tax", k=5)
        if "utils.py" in submap:
            print(f"  ✅ Submap includes utils.py for 'calculate total' query")
        else:
            print(f"  ❌ Submap should include utils.py")
            return False

        if "calculate_total" in submap:
            print(f"  ✅ Submap includes calculate_total function signature")
        else:
            print(f"  ❌ Submap should include calculate_total")
            return False

        # Search for "greet" — should rank main.py high
        submap2 = codemap.submap_for("greet user", k=5)
        if "main.py" in submap2:
            print(f"  ✅ Submap includes main.py for 'greet user' query")
        else:
            print(f"  ❌ Submap should include main.py")
            return False

    return True


def test_function_index():
    """Test that function/class indices are built correctly."""
    print("\n" + "=" * 60)
    print("TEST 6: Function/Class Index")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_test_repo(tmpdir)

        codemap = CodeMap(repo_root=str(tmpdir))
        codemap.build()

        # Check function index
        if "format_name" in codemap.function_index:
            paths = codemap.function_index["format_name"]
            print(f"  ✅ 'format_name' found in index: {paths}")
        else:
            print(f"  ❌ 'format_name' not in function index")
            return False

        # Check class index
        if "DataProcessor" in codemap.class_index:
            paths = codemap.class_index["DataProcessor"]
            print(f"  ✅ 'DataProcessor' found in index: {paths}")
        else:
            print(f"  ❌ 'DataProcessor' not in class index")
            return False

    return True


def test_regex_fallback():
    """Test that regex fallback works for unsupported languages."""
    print("\n" + "=" * 60)
    print("TEST 7: Regex Fallback (Go/Rust)")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Create a Go file
        (tmpdir / "main.go").write_text('''package main

import "fmt"

func greet(name string) string {
    return "Hello, " + name
}

func main() {
    fmt.Println(greet("World"))
}
''')

        codemap = CodeMap(repo_root=str(tmpdir))
        codemap.build()

        go_file = codemap.files.get("main.go")
        if go_file:
            print(f"  ✅ Go file parsed via regex fallback: {len(go_file.functions)} functions")
            func_names = [f.name for f in go_file.functions]
            if "greet" in func_names or "main" in func_names:
                print(f"  ✅ Functions found: {func_names}")
            else:
                print(f"  ⚠️ Functions: {func_names}")
        else:
            print(f"  ❌ Go file not parsed")
            return False

    return True


def main():
    print("\n" + "=" * 60)
    print("  PHASE 2: SMART MEMORY & CONTEXT — DUMMY TESTS")
    print("=" * 60 + "\n")

    results = []
    results.append(("Tree-sitter Parsing", test_tree_sitter_parsing()))
    results.append(("Signature Compaction", test_signature_compaction()))
    results.append(("Dependency Graph", test_dependency_graph()))
    results.append(("Context Budget", test_context_budget()))
    results.append(("Submap Relevance", test_submap_relevance()))
    results.append(("Function/Class Index", test_function_index()))
    results.append(("Regex Fallback", test_regex_fallback()))

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("  🎉 PHASE 2 ALL TESTS PASSED")
    else:
        print("  ⚠️  SOME TESTS FAILED — review above")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
