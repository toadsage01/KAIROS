"""
Search tools — grep, glob.

grep: Search file contents using regex (uses ripgrep if available,
falls back to Python re module).
glob: Find files by name pattern (uses pathlib.glob).

Both are read-only (SAFE permission).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tools.base import BaseTool, ToolContext, ToolPermission, ToolResult, validate_path


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search for a regex pattern in file contents. Returns matching lines "
        "with file paths and line numbers. Searches recursively from the "
        "given directory (default: workspace root)."
    )
    schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression to search for",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: '.')",
            },
            "include": {
                "type": "string",
                "description": "File extension filter (e.g. '*.py'). Default: all files.",
            },
        },
        "required": ["pattern"],
    }
    permission = ToolPermission.SAFE

    def execute(self, ctx: ToolContext, pattern: str, path: str = ".", include: str = "") -> ToolResult:
        base = ctx.worktree_path or ctx.workspace_path
        try:
            resolved = validate_path(path, base)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        if not resolved.exists():
            return ToolResult(success=False, output="", error=f"path not found: {path}")

        # Try ripgrep first (much faster)
        rg_path = shutil.which("rg")
        if rg_path:
            return self._grep_ripgrep(rg_path, resolved, pattern, include, base)

        # Fallback to Python re
        return self._grep_python(resolved, pattern, include, base)

    def _grep_ripgrep(self, rg: str, search_path: Path, pattern: str, include: str, base: Path) -> ToolResult:
        args = [rg, "--line-number", "--no-heading", "--color=never"]
        if include:
            args.extend(["--glob", include])
        args.extend(["--", pattern, str(search_path)])

        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=30)
            if result.returncode not in (0, 1):  # 0=found, 1=not found
                return ToolResult(success=False, output="", error=result.stderr)

            if not result.stdout.strip():
                return ToolResult(success=True, output="(no matches)")

            # Truncate if too long
            output = result.stdout
            if len(output) > 10000:
                output = output[:10000] + f"\n... (truncated, {len(result.stdout)} chars total)"

            return ToolResult(success=True, output=output)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="grep timed out")
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))

    def _grep_python(self, search_path: Path, pattern: str, include: str, base: Path) -> ToolResult:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(success=False, output="", error=f"invalid regex: {e}")

        results: list[str] = []
        try:
            if search_path.is_file():
                files = [search_path]
            else:
                files = []
                for p in search_path.rglob("*"):
                    if not p.is_file():
                        continue
                    if ".git" in p.parts or "__pycache__" in p.parts or ".venv" in p.parts:
                        continue
                    if include:
                        from fnmatch import fnmatch
                        if not fnmatch(p.name, include):
                            continue
                    files.append(p)

            for f in files:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    for i, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            rel = f.relative_to(base)
                            results.append(f"{rel}:{i}: {line}")
                            if len(results) >= 500:
                                results.append("... (truncated at 500 matches)")
                                return ToolResult(success=True, output="\n".join(results))
                except Exception:
                    continue

            if not results:
                return ToolResult(success=True, output="(no matches)")

            return ToolResult(success=True, output="\n".join(results))
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))


class GlobTool(BaseTool):
    name = "glob"
    description = (
        "Find files by name pattern. Uses shell-style globbing "
        "(e.g. '**/*.py' for all Python files). Returns matching file paths."
    )
    schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts')",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: '.')",
            },
        },
        "required": ["pattern"],
    }
    permission = ToolPermission.SAFE

    def execute(self, ctx: ToolContext, pattern: str, path: str = ".") -> ToolResult:
        base = ctx.worktree_path or ctx.workspace_path
        try:
            resolved = validate_path(path, base)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        if not resolved.exists():
            return ToolResult(success=False, output="", error=f"path not found: {path}")

        try:
            matches = []
            for p in resolved.glob(pattern):
                if ".git" in p.parts or ".worktrees" in p.parts:
                    continue
                if "__pycache__" in p.parts or ".venv" in p.parts:
                    continue
                rel = p.relative_to(base)
                matches.append(str(rel))

            if not matches:
                return ToolResult(success=True, output="(no matches)")

            matches.sort()
            if len(matches) > 500:
                output = "\n".join(matches[:500]) + f"\n... (truncated, {len(matches)} total)"
            else:
                output = "\n".join(matches)

            return ToolResult(
                success=True,
                output=output,
                data={"count": len(matches)},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))
