"""
ToolAgent — base class for agents that can use tools.

Extends BaseAgent with optional tool support. Subclasses define:
  - use_tools: bool — whether to use tool loop (default False = single-pass)
  - allowed_tools: list[str] — which tools this agent can use

When use_tools=True AND ctx.tool_registry is set, the agent runs a tool
loop (native for cloud APIs, ReAct for web bridges). Otherwise, it falls
back to single-pass mode (backward compatible with BaseAgent).

Subclasses still implement build_prompt() and write_output() exactly as
before. The tool loop is transparent — write_output() receives the final
model output, same as single-pass mode.
"""
from __future__ import annotations

from typing import Any

from agents.base import AgentContext, BaseAgent


class ToolAgent(BaseAgent):
    """Base class for tool-enabled agents.

    Set use_tools=True in subclass to enable the tool loop.
    Set allowed_tools to restrict which tools the agent can call.

    Example:
        class CoderAgent(ToolAgent):
            name = "coder"
            use_tools = True
            allowed_tools = ["read_file", "write_file", "edit_file",
                             "list_dir", "execute", "git_status", "git_diff"]
    """
    use_tools: bool = False
    allowed_tools: list[str] = []

    def run(self, ctx: AgentContext) -> str:
        """Run the agent. Uses tool loop if configured, else single-pass.

        The tool loop is only activated when ALL of:
          - self.use_tools is True
          - ctx.tool_registry is not None
          - ctx.workspace_path is not None
        Otherwise, falls back to BaseAgent.run() (single-pass).
        """
        if not self.use_tools or ctx.tool_registry is None or ctx.workspace_path is None:
            # Single-pass mode (backward compatible)
            return super().run(ctx)

        # Tool loop mode
        return self._run_with_tools(ctx)

    def _run_with_tools(self, ctx: AgentContext) -> str:
        """Run the agent with a tool loop.

        Uses route_with_tools() which automatically detects:
          - Cloud API (no api_base) → native function calling
          - Web bridge (has api_base) → ReAct text-based tool calling
        """
        from llm.router_tools import route_with_tools
        from tools.base import ToolContext

        # Build the prompt (same as single-pass)
        prompt = self.build_prompt(ctx)

        # Create ToolContext from AgentContext
        worktree_path = ctx.worktree.path if ctx.worktree else None
        tool_ctx = ToolContext(
            workspace_path=ctx.workspace_path,
            worktree_path=worktree_path,
            state=ctx.state,
            hitl_callback=None,  # v1: no HITL for tools (worktree isolation)
        )

        # Run with tools
        out = route_with_tools(
            agent_name=self.name,
            prompt=prompt,
            tool_registry=ctx.tool_registry,
            tool_ctx=tool_ctx,
            allowed_tools=self.allowed_tools,
            agents=self.agents_cfg,
            extra_context=self.extra_context(ctx),
            template_vars=self.template_vars(ctx),
        )

        # Write output (same as single-pass)
        path = self.write_output(ctx, out)
        self.state.append_log(
            f"agent={self.name} task={ctx.task_id} wrote={path} (tool-loop)"
        )
        return path
