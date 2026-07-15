"""
Native tool calling support — for cloud APIs that support the `tools` parameter.

This is a SEPARATE module from llm/router.py to avoid touching the user's
version (which has Jinja2 rendering, streaming, template_vars, etc.).

Provides:
  - route_with_tools(): Native function calling for Groq/Gemini API
  - Falls back to llm/tool_loop.py (ReAct) for web bridge endpoints

Usage:
  from llm.router_tools import route_with_tools
  result = route_with_tools(
      agent_name="coder",
      prompt="Add a power function",
      tool_registry=registry,
      tool_ctx=ctx,
      allowed_tools=["read_file", "write_file", "run_tests"],
  )
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from llm.router import (
    AgentConfig,
    ModelEndpoint,
    _load_prompt,
    _render_prompt_template,
    _log_success,
    _log_fallback,
    _log_prompt_response,
    _mock_response,
    _validate_response,
    load_agents,
    _HAS_LITELLM,
)


def _is_web_bridge(endpoint: ModelEndpoint) -> bool:
    """Check if an endpoint is a web bridge (has api_base) vs cloud API."""
    return bool(endpoint.api_base)


def route_with_tools(
    agent_name: str,
    prompt: str,
    tool_registry: Any,
    tool_ctx: Any,  # ToolContext
    allowed_tools: list[str],
    agents: dict[str, AgentConfig] | None = None,
    extra_context: str = "",
    template_vars: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    json_mode: bool = False,
) -> str:
    """Run an agent with tool support.

    For cloud APIs (Groq, Gemini): uses native function calling.
    For web bridges (WebAI2API): uses ReAct text-based tool calling.

    The function automatically detects which mode to use based on whether
    the endpoint has an api_base (web bridge) or not (cloud API).

    Args:
        agent_name: Name of the agent
        prompt: User prompt (task description)
        tool_registry: ToolRegistry instance
        tool_ctx: ToolContext (workspace path, worktree path, etc.)
        allowed_tools: List of tool names this agent can use
        agents: Agent configs (loaded from agents.yaml if None)
        extra_context: Extra context for system prompt
        template_vars: Jinja2 variables for system prompt rendering
        conversation_id: If set, passed to WebAI2API for session continuity
        json_mode: If True, injects strict JSON output directive

    Returns:
        The final model output (text — code blocks, STATUS:, etc.)
    """
    if agents is None:
        agents = load_agents()
    cfg = agents.get(agent_name)
    if cfg is None:
        raise KeyError(f"unknown agent: {agent_name}")

    # Try each endpoint in the fallback chain
    chain = [
        ("primary", cfg.primary),
        ("fallback", cfg.fallback),
        ("fallback_2", cfg.fallback_2),
    ]

    last_err: Exception | None = None
    for i, (label, endpoint) in enumerate(chain):
        if endpoint is None:
            continue

        try:
            if _is_web_bridge(endpoint):
                # Web bridge → ReAct text-based tool calling
                from llm.tool_loop import react_loop
                out = react_loop(
                    agent_name=agent_name,
                    prompt=prompt,
                    cfg=cfg,
                    tool_registry=tool_registry,
                    tool_ctx=tool_ctx,
                    allowed_tools=allowed_tools,
                    template_vars=template_vars,
                    extra_context=extra_context,
                    conversation_id=conversation_id,
                    json_mode=json_mode,
                )
            else:
                # Cloud API → native function calling
                out = _native_tool_loop(
                    agent_name, endpoint, cfg, prompt,
                    tool_registry, tool_ctx, allowed_tools,
                    template_vars, extra_context,
                )

            _log_success(agent_name, endpoint, is_mock=False)
            # Log the final prompt + response
            system = _build_system(cfg, template_vars, extra_context)
            _log_prompt_response(agent_name, endpoint, system, prompt, out)
            return out

        except Exception as e:  # noqa: BLE001
            last_err = e
            next_label = chain[i + 1][0] if i + 1 < len(chain) else None
            _log_fallback(agent_name, endpoint, e, next_label)
            continue

    # All endpoints failed
    if cfg.allow_mock:
        _log_success(agent_name, ModelEndpoint(model="mock"), is_mock=True)
        return _mock_response(agent_name, prompt, cfg.role)
    raise RuntimeError(
        f"agent {agent_name}: all providers failed in route_with_tools. last_err={last_err}"
    )


def _build_system(
    cfg: AgentConfig,
    template_vars: dict[str, Any] | None,
    extra_context: str,
) -> str:
    """Build the system prompt (same logic as router.route)."""
    system_template = (
        _load_prompt(cfg.system_prompt_file) if cfg.system_prompt_file else cfg.role
    )
    system = _render_prompt_template(system_template, template_vars or {})
    if extra_context:
        system = f"{system}\n\n## Context\n{extra_context}"
    return system


def _native_tool_loop(
    agent_name: str,
    endpoint: ModelEndpoint,
    cfg: AgentConfig,
    prompt: str,
    tool_registry: Any,
    tool_ctx: Any,
    allowed_tools: list[str],
    template_vars: dict[str, Any] | None,
    extra_context: str,
    max_iterations: int = 10,
) -> str:
    """Run a native tool-calling loop with a cloud API (Groq/Gemini).

    Uses LiteLLM's `tools` parameter for function calling. The model
    returns structured tool_calls, we execute them, and feed results back.
    """
    if not _HAS_LITELLM:
        raise RuntimeError("litellm not installed")

    import litellm

    system = _build_system(cfg, template_vars, extra_context)

    # Get tool schemas in OpenAI format
    tool_schemas = tool_registry.list_schemas(allowed_tools)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    for iteration in range(max_iterations):
        kwargs: dict[str, Any] = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "num_retries": endpoint.num_retries,
            "request_timeout": endpoint.request_timeout,
            "tools": tool_schemas,
            "stream": False,  # non-streaming for tool loop
        }

        response = litellm.completion(**kwargs)
        message = response.choices[0].message

        # Check if model wants to call tools
        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            # No tool calls — this is the final answer
            content = message.content or ""
            return _validate_response(content, endpoint)

        # Execute tool calls
        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            tool_name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                arguments = {}

            # Execute via registry
            result = tool_registry.execute(tool_name, tool_ctx, **arguments)

            # Log
            try:
                tool_ctx.state.append_log(
                    f"tool_call: agent={agent_name} tool={tool_name} "
                    f"success={result.success} iter={iteration + 1}"
                )
            except Exception:
                pass

            # Add tool result to conversation
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result.to_llm_text(),
            })

    # Max iterations reached
    return f"(reached max tool iterations: {max_iterations})"
