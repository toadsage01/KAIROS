"""
Tool Registry — central registry for all tools.

Agents query the registry to discover available tools. The framework
dispatches tool calls through the registry, which handles:
  - Permission checks (SAFE/MODERATE/DANGEROUS)
  - HITL gating for DANGEROUS tools
  - Execution and result formatting
  - Logging (to myforge state + logs/tool_calls.log)

The registry is initialized at startup with built-in tools, then extended
with MCP server tools (loaded from config/mcp.yaml).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from tools.base import BaseTool, ToolContext, ToolPermission, ToolResult


class ToolRegistry:
    """Central registry for all tools available to agents.
    
    Usage:
        registry = ToolRegistry()
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        
        # Agent wants to call a tool
        result = registry.execute("read_file", ctx, path="foo.py")
        
        # Get schemas for native function calling (Groq/Gemini)
        schemas = registry.list_schemas(["read_file", "write_file"])
        
        # Get text descriptions for ReAct (web bridge)
        desc = registry.list_react_descriptions(["read_file"])
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    # ---------- registration ----------
    def register(self, tool: BaseTool) -> None:
        """Register a tool. Overwrites if name already exists."""
        if not tool.name:
            raise ValueError(f"tool has no name: {tool}")
        self._tools[tool.name] = tool

    def register_all(self, tools: list[BaseTool]) -> None:
        """Register multiple tools at once."""
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> bool:
        """Remove a tool from the registry."""
        return self._tools.pop(name, None) is not None

    # ---------- query ----------
    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        """List all registered tool names."""
        return sorted(self._tools.keys())

    def list_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        """Get OpenAI-format schemas for native function calling.
        
        Args:
            names: Optional list of tool names. If None, returns all.
        """
        if names is None:
            names = self.list_names()
        return [
            self._tools[name].to_openai_schema()
            for name in names
            if name in self._tools
        ]

    def list_react_descriptions(self, names: list[str] | None = None) -> str:
        """Get text descriptions for ReAct-style text-based tool calling.
        
        Returns a single string listing all tools and their parameters.
        Used in system prompts for web bridge agents.
        """
        if names is None:
            names = self.list_names()
        descs = [
            self._tools[name].to_react_description()
            for name in names
            if name in self._tools
        ]
        return "\n---\n".join(descs)

    # ---------- execution ----------
    def execute(
        self,
        name: str,
        ctx: ToolContext,
        **kwargs,
    ) -> ToolResult:
        """Execute a tool by name.
        
        Handles:
          - Tool lookup (returns error if not found)
          - Permission check (DANGEROUS tools require HITL approval)
          - Execution (catches all exceptions)
          - Logging (to logs/tool_calls.log)
        
        Returns ToolResult always (never raises).
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"unknown tool: {name}",
            )

        # Permission check: DANGEROUS tools require HITL approval
        if tool.permission == ToolPermission.DANGEROUS:
            approval = self._check_dangerous_approval(name, tool, ctx, kwargs)
            if not approval:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"DANGEROUS tool '{name}' not approved by user",
                )

        # Execute with full error handling
        start = time.time()
        try:
            result = tool.execute(ctx, **kwargs)
        except Exception as e:  # noqa: BLE001
            result = ToolResult(
                success=False,
                output="",
                error=f"{type(e).__name__}: {e}",
            )

        elapsed = time.time() - start
        self._log_call(name, kwargs, result, elapsed, ctx)
        return result

    # ---------- internal ----------
    def _check_dangerous_approval(
        self,
        tool_name: str,
        tool: BaseTool,
        ctx: ToolContext,
        kwargs: dict,
    ) -> bool:
        """Check if a DANGEROUS tool has been approved.
        
        For v1: if ctx.hitl_callback is set, call it with the tool info.
        The callback returns True (approved) or False (rejected/pending).
        
        If no callback is set, default to DENY (safer).
        """
        if ctx.hitl_callback is None:
            # No callback — deny by default for safety
            return False

        try:
            request = {
                "tool": tool_name,
                "description": tool.description,
                "permission": tool.permission.value,
                "arguments": kwargs,
            }
            return bool(ctx.hitl_callback(request))
        except Exception:
            return False

    def _log_call(
        self,
        name: str,
        kwargs: dict,
        result: ToolResult,
        elapsed: float,
        ctx: ToolContext,
    ) -> None:
        """Log tool call to logs/tool_calls.log for debugging."""
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "tool_calls.log"

        # Truncate large outputs in log
        output_preview = result.output[:500] if result.output else ""
        if len(result.output or "") > 500:
            output_preview += f"... ({len(result.output)} chars total)"

        entry = (
            f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] "
            f"tool={name} args={json.dumps(kwargs, default=str)[:200]} "
            f"success={result.success} elapsed={elapsed:.2f}s "
            f"error={result.error or 'none'} "
            f"output_preview={output_preview!r}\n"
        )
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)


# ---------- singleton ----------
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the global ToolRegistry singleton.
    
    Initialized on first call with all built-in tools.
    MCP tools are loaded separately by tools/mcp_loader.py.
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_builtins(_registry)
    return _registry


def _register_builtins(registry: ToolRegistry) -> None:
    """Register all built-in tools."""
    from tools.builtins.filesystem import (
        ReadFileTool, WriteFileTool, EditFileTool, ListDirTool, MkdirTool,
    )
    from tools.builtins.terminal import ExecuteTool, BackgroundJobTool
    from tools.builtins.git import (
        GitStatusTool, GitDiffTool, GitLogTool, GitCommitTool, GitBranchTool,
    )
    from tools.builtins.search import GrepTool, GlobTool

    registry.register_all([
        # Filesystem (5)
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        ListDirTool(),
        MkdirTool(),
        # Terminal (2)
        ExecuteTool(),
        BackgroundJobTool(),
        # Git (5)
        GitStatusTool(),
        GitDiffTool(),
        GitLogTool(),
        GitCommitTool(),
        GitBranchTool(),
        # Search (2)
        GrepTool(),
        GlobTool(),
    ])
