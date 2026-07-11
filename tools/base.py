"""
Tool framework foundation — BaseTool, ToolResult, ToolContext, ToolPermission.

Design principles:
  - Tools are stateless. The framework provides context (workspace path, state).
  - Each tool has a JSON schema (for native function calling) AND a text
    description (for ReAct-style text-based tool calling).
  - Permissions classify risk level: SAFE (read-only), MODERATE (writes),
    DANGEROUS (destructive — requires HITL approval).
  - Path safety: all filesystem tools validate paths stay within workspace.

Usage:
  registry = ToolRegistry()
  registry.register(ReadFileTool())
  result = registry.execute("read_file", ctx, path="foo.py")
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ToolPermission(str, Enum):
    """Risk classification for tools.
    
    SAFE: Always execute. Read-only operations.
    MODERATE: Execute in worktree, log to UI. Writes, commits.
    DANGEROUS: Require HITL approval before execution. Deletes, destructive commands.
    """
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"


@dataclass
class ToolResult:
    """Result of a tool execution. Returned to both the LLM (as text) and
    the framework (as structured data)."""
    success: bool
    output: str  # text output for the LLM
    error: str | None = None
    data: dict[str, Any] | None = None  # structured data for framework use

    def to_llm_text(self) -> str:
        """Format for injection into LLM context (ReAct mode)."""
        if self.success:
            return self.output if self.output else "(success, no output)"
        return f"ERROR: {self.error or 'unknown error'}"


@dataclass
class ToolContext:
    """Framework-provided context for tool execution.
    
    Passed to every tool.execute() call. Provides workspace path, optional
    worktree path (for per-task isolation), and myforge state access.
    """
    workspace_path: Path          # the target repo root
    worktree_path: Path | None    # current task's worktree (if in worktree mode)
    state: Any | None = None      # FileState instance (for reading/writing myforge state)
    hitl_callback: Any | None = None  # callable(hitl_request) for DANGEROUS tools


def validate_path(path: str, base: Path) -> Path:
    """Validate that a path is relative and stays within base.
    
    Mirrors the safety pattern from core/workspace.py:
      - Reject absolute paths
      - Reject ".." traversal
      - Verify resolved path is within base
    
    Returns the resolved Path on success, raises ValueError on failure.
    """
    cleaned = Path(path.strip().strip("\"'"))
    if cleaned.is_absolute():
        raise ValueError(f"unsafe path (absolute): {path}")
    if ".." in cleaned.parts:
        raise ValueError(f"unsafe path (traversal): {path}")
    resolved = (base / cleaned).resolve()
    base_resolved = base.resolve()
    if base_resolved not in resolved.parents and resolved != base_resolved:
        raise ValueError(f"path escapes workspace: {path}")
    return resolved


class BaseTool(ABC):
    """Abstract base class for all tools.
    
    Subclasses must define:
      - name: short identifier (e.g. "read_file")
      - description: what the tool does (for LLM)
      - schema: JSON schema for parameters (for native function calling)
      - permission: risk level
      - execute(): the actual implementation
    
    The schema describes ONLY the parameters the LLM provides. The framework
    provides ToolContext separately.
    """
    name: str = ""
    description: str = ""
    schema: dict[str, Any] = {}
    permission: ToolPermission = ToolPermission.SAFE

    @abstractmethod
    def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        """Execute the tool. Framework provides ctx, LLM provides kwargs."""
        ...

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format for native tool calling.
        
        Used by Groq, Gemini API, and other providers that support
        native function calling.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            }
        }

    def to_react_description(self) -> str:
        """Convert to text description for ReAct-style text-based tool calling.
        
        Used by web bridge agents (WebAI2API) that don't support native
        function calling. The LLM outputs tool calls as text, the framework
        parses them.
        """
        import json
        params_desc = json.dumps(self.schema.get("properties", {}), indent=2)
        return (
            f"Tool: {self.name}\n"
            f"Description: {self.description}\n"
            f"Parameters: {params_desc}\n"
            f"Permission: {self.permission.value}"
        )
