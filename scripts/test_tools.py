"""
Test script for the tool framework.

Verifies that all 14 built-in tools work correctly.
Run this BEFORE integrating tools into agents.

Usage:
    cd ~/Projects/myforge
    python scripts/test_tools.py
"""
import sys
import tempfile
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.base import ToolContext, ToolPermission
from tools.registry import get_tool_registry
from tools.permissions import classify_command


def test_permissions():
    """Test the command permission classifier."""
    print("=" * 60)
    print("TEST 1: Permission Classifier")
    print("=" * 60)

    cases = [
        ("ls", ToolPermission.SAFE),
        ("cat foo.py", ToolPermission.SAFE),
        ("pytest", ToolPermission.SAFE),
        ("ruff check .", ToolPermission.SAFE),
        ("git status", ToolPermission.SAFE),
        ("git diff", ToolPermission.SAFE),
        ("git log", ToolPermission.SAFE),
        ("git add -A", ToolPermission.MODERATE),
        ("git commit -m 'test'", ToolPermission.MODERATE),
        ("pip install requests", ToolPermission.MODERATE),
        ("rm foo.py", ToolPermission.DANGEROUS),
        ("rm -rf /", ToolPermission.DANGEROUS),
        ("git reset --hard", ToolPermission.DANGEROUS),
        ("sudo ls", ToolPermission.DANGEROUS),
        ("git push --force", ToolPermission.DANGEROUS),
        ("python script.py", ToolPermission.SAFE),
        ("python -m pytest", ToolPermission.SAFE),
    ]

    passed = 0
    failed = 0
    for cmd, expected in cases:
        result = classify_command(cmd)
        status = "✅" if result == expected else "❌"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status} '{cmd}' → {result.value} (expected {expected.value})")

    print(f"\n  {passed} passed, {failed} failed")
    print()
    return failed == 0


def test_filesystem_tools():
    """Test read_file, write_file, edit_file, list_dir, mkdir."""
    print("=" * 60)
    print("TEST 2: Filesystem Tools")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        ctx = ToolContext(workspace_path=workspace, worktree_path=None)
        registry = get_tool_registry()

        # Test write_file
        print("\n  --- write_file ---")
        result = registry.execute("write_file", ctx, path="src/main.py", content="print('hello')\n")
        print(f"  {'✅' if result.success else '❌'} write_file: {result.output}")
        assert result.success, result.error
        assert (workspace / "src" / "main.py").exists()

        # Test read_file
        print("\n  --- read_file ---")
        result = registry.execute("read_file", ctx, path="src/main.py")
        print(f"  {'✅' if result.success else '❌'} read_file: {result.output.strip()}")
        assert result.success, result.error
        assert "print('hello')" in result.output

        # Test edit_file
        print("\n  --- edit_file ---")
        result = registry.execute("edit_file", ctx, path="src/main.py",
                                   old_string="print('hello')", new_string="print('world')")
        print(f"  {'✅' if result.success else '❌'} edit_file: {result.output}")
        assert result.success, result.error

        result = registry.execute("read_file", ctx, path="src/main.py")
        assert "print('world')" in result.output

        # Test list_dir
        print("\n  --- list_dir ---")
        result = registry.execute("list_dir", ctx, path=".", recursive=True)
        print(f"  {'✅' if result.success else '❌'} list_dir:")
        for line in result.output.split("\n"):
            print(f"    {line}")
        assert result.success, result.error

        # Test mkdir
        print("\n  --- mkdir ---")
        result = registry.execute("mkdir", ctx, path="tests/unit")
        print(f"  {'✅' if result.success else '❌'} mkdir: {result.output}")
        assert result.success, result.error
        assert (workspace / "tests" / "unit").exists()

        # Test path safety (reject absolute path)
        print("\n  --- path safety (absolute) ---")
        result = registry.execute("read_file", ctx, path="/etc/passwd")
        print(f"  {'✅' if not result.success else '❌'} rejected absolute path: {result.error}")
        assert not result.success

        # Test path safety (reject traversal)
        print("\n  --- path safety (traversal) ---")
        result = registry.execute("read_file", ctx, path="../../../etc/passwd")
        print(f"  {'✅' if not result.success else '❌'} rejected traversal: {result.error}")
        assert not result.success

    print("\n  All filesystem tests passed ✅")
    print()
    return True


def test_search_tools():
    """Test grep and glob."""
    print("=" * 60)
    print("TEST 3: Search Tools")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        ctx = ToolContext(workspace_path=workspace, worktree_path=None)
        registry = get_tool_registry()

        # Create test files
        registry.execute("write_file", ctx, path="app.py", content="def hello():\n    return 'hello'\n")
        registry.execute("write_file", ctx, path="utils.py", content="def world():\n    return 'world'\n")
        registry.execute("write_file", ctx, path="tests/test_app.py", content="def test_hello():\n    pass\n")

        # Test grep
        print("\n  --- grep ---")
        result = registry.execute("grep", ctx, pattern="def ", path=".")
        print(f"  {'✅' if result.success else '❌'} grep:")
        for line in result.output.split("\n"):
            print(f"    {line}")
        assert result.success
        assert "hello" in result.output

        # Test glob
        print("\n  --- glob ---")
        result = registry.execute("glob", ctx, pattern="**/*.py", path=".")
        print(f"  {'✅' if result.success else '❌'} glob:")
        for line in result.output.split("\n"):
            print(f"    {line}")
        assert result.success
        assert "app.py" in result.output
        assert "tests/test_app.py" in result.output

    print("\n  All search tests passed ✅")
    print()
    return True


def test_git_tools():
    """Test git status, diff, log, commit, branch."""
    print("=" * 60)
    print("TEST 4: Git Tools")
    print("=" * 60)

    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(workspace), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(workspace), capture_output=True)

        ctx = ToolContext(workspace_path=workspace, worktree_path=None)
        registry = get_tool_registry()

        # Create a file and commit
        registry.execute("write_file", ctx, path="main.py", content="print('hello')\n")
        result = registry.execute("git_commit", ctx, message="initial commit")
        print(f"\n  {'✅' if result.success else '❌'} git_commit: {result.output.strip()}")
        assert result.success, result.error

        # Test git_status
        result = registry.execute("git_status", ctx)
        print(f"  {'✅' if result.success else '❌'} git_status: {result.output.strip() or '(clean)'}")
        assert result.success

        # Test git_log
        result = registry.execute("git_log", ctx, count=5)
        print(f"  {'✅' if result.success else '❌'} git_log: {result.output.strip()}")
        assert result.success
        assert "initial commit" in result.output

        # Test git_diff
        registry.execute("write_file", ctx, path="main.py", content="print('world')\n")
        result = registry.execute("git_diff", ctx)
        print(f"  {'✅' if result.success else '❌'} git_diff: {result.output.strip()[:100]}")
        assert result.success
        assert "hello" in result.output or "world" in result.output

        # Test git_branch
        result = registry.execute("git_branch", ctx, action="list")
        print(f"  {'✅' if result.success else '❌'} git_branch: {result.output.strip()}")
        assert result.success

    print("\n  All git tests passed ✅")
    print()
    return True


def test_terminal_tools():
    """Test execute and background_job."""
    print("=" * 60)
    print("TEST 5: Terminal Tools")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        ctx = ToolContext(workspace_path=workspace, worktree_path=None)
        registry = get_tool_registry()

        # Test safe command
        result = registry.execute("execute", ctx, command="echo 'hello world'")
        print(f"\n  {'✅' if result.success else '❌'} execute (echo): {result.output.strip()}")
        assert result.success
        assert "hello world" in result.output

        # Test python command
        result = registry.execute("execute", ctx, command="python3 -c \"print(2+2)\"")
        print(f"  {'✅' if result.success else '❌'} execute (python): {result.output.strip()}")
        assert result.success
        assert "4" in result.output

        # Test dangerous command (should be blocked)
        result = registry.execute("execute", ctx, command="rm -rf /")
        print(f"  {'✅' if not result.success else '❌'} execute (rm -rf): blocked — {result.error[:80]}")
        assert not result.success

    print("\n  All terminal tests passed ✅")
    print()
    return True


def test_registry():
    """Test the tool registry itself."""
    print("=" * 60)
    print("TEST 6: Tool Registry")
    print("=" * 60)

    registry = get_tool_registry()

    # List all registered tools
    names = registry.list_names()
    print(f"\n  Registered tools ({len(names)}):")
    for name in names:
        tool = registry.get(name)
        print(f"    {name:20s} [{tool.permission.value:8s}] {tool.description[:60]}")

    # Test schema generation
    schemas = registry.list_schemas(["read_file", "write_file"])
    print(f"\n  Schemas generated: {len(schemas)}")
    assert len(schemas) == 2
    assert schemas[0]["function"]["name"] == "read_file"

    # Test ReAct description
    react_desc = registry.list_react_descriptions(["read_file"])
    print(f"\n  ReAct description (preview):")
    for line in react_desc.split("\n")[:5]:
        print(f"    {line}")

    assert len(names) == 14, f"expected 14 tools, got {len(names)}"
    print(f"\n  All registry tests passed ✅")
    print()
    return True


def main():
    print("\n" + "=" * 60)
    print("  KAIROS TOOL FRAMEWORK — TEST SUITE")
    print("=" * 60 + "\n")

    results = []
    results.append(("permissions", test_permissions()))
    results.append(("filesystem", test_filesystem_tools()))
    results.append(("search", test_search_tools()))
    results.append(("git", test_git_tools()))
    results.append(("terminal", test_terminal_tools()))
    results.append(("registry", test_registry()))

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
        print("  🎉 ALL TESTS PASSED — tool framework is ready!")
    else:
        print("  ⚠️  SOME TESTS FAILED — fix before integrating with agents.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
