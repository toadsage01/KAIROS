"""
Phase 4 — MCP (Model Context Protocol) client.

Uses the official `mcp` Python SDK when available. Without it, all calls
return a clear "mcp not installed" error so agents degrade gracefully.

Pattern: each tool call is ONE round-trip. We do NOT keep a persistent
session per agent — that would defeat the file-driven blackboard design.
Open a session, call a tool, close. Bounded I/O.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

try:
    from mcp import ClientSession, StdioServerParameters  # type: ignore
    from mcp.client.stdio import stdio_client  # type: ignore
    _HAS_MCP = True
except ImportError:
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore
    stdio_client = None  # type: ignore
    _HAS_MCP = False


@dataclass
class MCPToolCall:
    tool: str
    args: dict[str, Any]


@dataclass
class MCPResult:
    ok: bool
    output: str
    error: str | None = None


class MCPClient:
    """One-shot MCP client. Each `call()` opens a fresh session.

    server_config example (in agents.yaml):
        mcp:
          command: "npx"
          args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    """

    def __init__(self, server_config: dict | None = None):
        self.server_config = server_config or {}
        self.available = _HAS_MCP and bool(self.server_config.get("command"))

    async def _call_async(self, tool: str, args: dict) -> MCPResult:
        if not _HAS_MCP:
            return MCPResult(ok=False, output="", error="mcp SDK not installed")
        if not self.server_config.get("command"):
            return MCPResult(ok=False, output="", error="no mcp server configured")
        try:
            server_params = StdioServerParameters(
                command=self.server_config["command"],
                args=self.server_config.get("args", []),
                env=self.server_config.get("env"),
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, args)
                    # Serialize the result content
                    if hasattr(result, "content"):
                        texts = []
                        for c in result.content:
                            if hasattr(c, "text"):
                                texts.append(c.text)
                            else:
                                texts.append(str(c))
                        return MCPResult(ok=True, output="\n".join(texts))
                    return MCPResult(ok=True, output=str(result))
        except Exception as e:  # noqa: BLE001
            return MCPResult(ok=False, output="", error=f"{type(e).__name__}: {e}")

    def call(self, tool: str, args: dict | None = None) -> MCPResult:
        """Synchronous wrapper. Runs the async call in an event loop."""
        return asyncio.run(self._call_async(tool, args or {}))

    def list_tools(self) -> list[str]:
        """Best-effort tool listing. Returns [] on any failure."""
        if not self.available:
            return []
        try:
            async def _list():
                server_params = StdioServerParameters(
                    command=self.server_config["command"],
                    args=self.server_config.get("args", []),
                    env=self.server_config.get("env"),
                )
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        r = await session.list_tools()
                        return [t.name for t in r.tools]
            return asyncio.run(_list())
        except Exception:
            return []


def load_mcp_client_from_env() -> MCPClient:
    """Build an MCPClient from env vars MYFORGE_MCP_COMMAND / _ARGS.

    MYFORGE_MCP_COMMAND=npx
    MYFORGE_MCP_ARGS=-y,@modelcontextprotocol/server-filesystem,/tmp
    """
    cmd = os.getenv("MYFORGE_MCP_COMMAND")
    if not cmd:
        return MCPClient(server_config=None)
    args_raw = os.getenv("MYFORGE_MCP_ARGS", "")
    args = [a.strip() for a in args_raw.split(",") if a.strip()]
    return MCPClient(server_config={"command": cmd, "args": args})
