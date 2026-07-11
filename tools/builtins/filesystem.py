"""
Filesystem tools — read_file, write_file, edit_file, list_dir, mkdir.

All tools operate WITHIN the workspace (or worktree if set). Path safety
is enforced via validate_path() — no absolute paths, no ".." traversal.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.base import BaseTool, ToolContext, ToolPermission, ToolResult, validate_path


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the content of a file. Returns the file's text content. "
        "Path must be relative to the workspace root."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file (e.g. 'src/main.py')",
            },
        },
        "required": ["path"],
    }
    permission = ToolPermission.SAFE

    def execute(self, ctx: ToolContext, path: str) -> ToolResult:
        base = ctx.worktree_path or ctx.workspace_path
        try:
            resolved = validate_path(path, base)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        if not resolved.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"file not found: {path}",
            )
        if not resolved.is_file():
            return ToolResult(
                success=False,
                output="",
                error=f"not a file: {path}",
            )

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
            return ToolResult(
                success=True,
                output=content,
                data={"path": str(resolved), "size": len(content)},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))


class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Write content to a file. Creates the file if it doesn't exist, "
        "overwrites if it does. Path must be relative to workspace root. "
        "Parent directories are created automatically."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file (e.g. 'src/main.py')",
            },
            "content": {
                "type": "string",
                "description": "The full content to write to the file",
            },
        },
        "required": ["path", "content"],
    }
    permission = ToolPermission.MODERATE

    def execute(self, ctx: ToolContext, path: str, content: str) -> ToolResult:
        base = ctx.worktree_path or ctx.workspace_path
        try:
            resolved = validate_path(path, base)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                output=f"wrote {len(content)} chars to {path}",
                data={"path": str(resolved), "size": len(content)},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Edit a file by replacing a specific string with a new string. "
        "Use this for targeted edits instead of rewriting the whole file. "
        "The old_string must appear exactly once in the file for safety."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find in the file (must be unique)",
            },
            "new_string": {
                "type": "string",
                "description": "The string to replace old_string with",
            },
        },
        "required": ["path", "old_string", "new_string"],
    }
    permission = ToolPermission.MODERATE

    def execute(self, ctx: ToolContext, path: str, old_string: str, new_string: str) -> ToolResult:
        base = ctx.worktree_path or ctx.workspace_path
        try:
            resolved = validate_path(path, base)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        if not resolved.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"file not found: {path}",
            )

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))

        # Count occurrences — require exactly 1 for safety
        count = content.count(old_string)
        if count == 0:
            return ToolResult(
                success=False,
                output="",
                error=f"old_string not found in {path}",
            )
        if count > 1:
            return ToolResult(
                success=False,
                output="",
                error=f"old_string found {count} times in {path} — must be unique. "
                      f"Use a longer/more specific old_string.",
            )

        # Replace and write
        new_content = content.replace(old_string, new_string, 1)
        try:
            resolved.write_text(new_content, encoding="utf-8")
            return ToolResult(
                success=True,
                output=f"edited {path}: replaced {len(old_string)} chars with {len(new_string)} chars",
                data={"path": str(resolved)},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))


class ListDirTool(BaseTool):
    name = "list_dir"
    description = (
        "List the contents of a directory. Returns file names, sizes, and "
        "types. Path must be relative to workspace root. Use '.' for root."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative directory path (e.g. 'src' or '.')",
            },
            "recursive": {
                "type": "boolean",
                "description": "If true, list recursively (default false)",
            },
        },
        "required": ["path"],
    }
    permission = ToolPermission.SAFE

    def execute(self, ctx: ToolContext, path: str, recursive: bool = False) -> ToolResult:
        base = ctx.worktree_path or ctx.workspace_path
        try:
            resolved = validate_path(path, base)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        if not resolved.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"directory not found: {path}",
            )
        if not resolved.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"not a directory: {path}",
            )

        try:
            entries = []
            if recursive:
                for p in sorted(resolved.rglob("*")):
                    if ".git" in p.parts or ".worktrees" in p.parts:
                        continue
                    if "__pycache__" in p.parts or ".venv" in p.parts:
                        continue
                    rel = p.relative_to(base)
                    entries.append({
                        "path": str(rel),
                        "type": "dir" if p.is_dir() else "file",
                        "size": p.stat().st_size if p.is_file() else 0,
                    })
            else:
                for p in sorted(resolved.iterdir()):
                    if p.name.startswith(".git"):
                        continue
                    rel = p.relative_to(base)
                    entries.append({
                        "path": str(rel),
                        "type": "dir" if p.is_dir() else "file",
                        "size": p.stat().st_size if p.is_file() else 0,
                    })

            # Format as readable text
            lines = []
            for e in entries:
                size_str = f" ({e['size']} bytes)" if e["type"] == "file" else "/"
                lines.append(f"{e['type']:4s} {e['path']}{size_str}")

            return ToolResult(
                success=True,
                output="\n".join(lines) if lines else "(empty directory)",
                data={"entries": entries, "count": len(entries)},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))


class MkdirTool(BaseTool):
    name = "mkdir"
    description = "Create a directory. Creates parent directories if needed."
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative directory path to create",
            },
        },
        "required": ["path"],
    }
    permission = ToolPermission.MODERATE

    def execute(self, ctx: ToolContext, path: str) -> ToolResult:
        base = ctx.worktree_path or ctx.workspace_path
        try:
            resolved = validate_path(path, base)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            resolved.mkdir(parents=True, exist_ok=True)
            return ToolResult(
                success=True,
                output=f"created directory: {path}",
                data={"path": str(resolved)},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(e))
