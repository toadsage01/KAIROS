"""
ReAct tool loop — for web bridge agents that don't support native tool calling.

Web bridges (WebAI2API, intense-rp) can't use the `tools` parameter in the
API request. Instead, we teach the model to output tool calls as XML tags,
parse them, execute, and feed results back.

Loop:
  1. Send system prompt (includes tool descriptions + format rules) + user prompt
  2. Model responds with either:
     a. <tool_call>{"name":"read_file","arguments":{"path":"foo.py"}}</tool_call>
     b. Final answer (code blocks, STATUS:, etc.)
     c. <done>summary</done>
  3. If tool_call → execute via registry, append <tool_result> to conversation
  4. Repeat until final answer or <done> or max_iterations

This is less reliable than native tool calling (70-90% vs 99%+) but works
with any LLM that can follow XML format instructions.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from llm.router import AgentConfig, ModelEndpoint, _load_prompt, _render_prompt_template
from tools.base import ToolContext, ToolResult


# Maximum tool call iterations before forcing a final answer
MAX_TOOL_ITERATIONS = 10

# XML tags for the ReAct protocol
TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)
DONE_RE = re.compile(r"<done>(.*?)</done>", re.DOTALL | re.IGNORECASE)
BLOCKED_RE = re.compile(r"<blocked>\s*(.*?)\s*</blocked>", re.DOTALL | re.IGNORECASE)


def _build_react_system_prompt(
    base_system: str,
    tool_descriptions: str,
) -> str:
    """Augment the system prompt with ReAct tool-calling instructions."""
    react_instructions = f"""

<tool_calling_protocol>
You have access to the following tools. To call a tool, output EXACTLY:

<tool_call>{{"name": "tool_name", "arguments": {{"param": "value"}}}}</tool_call>

Wait for the result before continuing. The result will appear as:

<tool_result>
{{result content}}
</tool_result>

You can call tools multiple times. When you have all the information you need,
output your FINAL answer (code blocks, STATUS:, etc.) WITHOUT any tool_call tags.

If you cannot complete the task, output:

<blocked>
One line explaining what's missing or ambiguous.
</blocked>

When you are completely finished, you may output:

<done>Brief summary of what you did.</done>

AVAILABLE TOOLS:
{tool_descriptions}
</tool_calling_protocol>
"""
    return base_system + react_instructions


def _extract_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract all <tool_call> JSON objects from the model's response."""
    calls = []
    for m in TOOL_CALL_RE.finditer(text):
        try:
            call = json.loads(m.group(1))
            if "name" in call:
                calls.append(call)
        except json.JSONDecodeError:
            # Try to fix common JSON issues
            raw = m.group(1).strip()
            # Sometimes models use single quotes
            try:
                raw_fixed = raw.replace("'", '"')
                call = json.loads(raw_fixed)
                if "name" in call:
                    calls.append(call)
            except json.JSONDecodeError:
                continue
    return calls


def _extract_final_answer(text: str) -> str:
    """Remove tool_call tags from the response, leaving only the final answer."""
    cleaned = TOOL_CALL_RE.sub("", text)
    # Also remove <done> tags but keep their content
    cleaned = DONE_RE.sub(r"\1", cleaned)
    return cleaned.strip()


def react_loop(
    agent_name: str,
    prompt: str,
    cfg: AgentConfig,
    tool_registry: Any,
    tool_ctx: ToolContext,
    allowed_tools: list[str],
    template_vars: dict[str, Any] | None = None,
    extra_context: str = "",
    conversation_id: str | None = None,
    json_mode: bool = False,
) -> str:
    """Run a ReAct tool loop with a web bridge model.

    Args:
        agent_name: Name of the agent (for logging)
        prompt: The user prompt (task description)
        cfg: AgentConfig (contains model endpoints, system prompt, etc.)
        tool_registry: ToolRegistry instance
        tool_ctx: ToolContext (workspace path, worktree path, etc.)
        allowed_tools: List of tool names this agent can use
        template_vars: Variables for Jinja2 system prompt rendering
        extra_context: Extra context to append to system prompt
        conversation_id: If set, passed to WebAI2API for session continuity
        json_mode: If True, injects strict JSON output directive

    Returns:
        The final model output (code blocks, STATUS:, etc.) with tool
        calls stripped out.
    """
    import litellm

    # Build the system prompt with tool descriptions
    system_template = (
        _load_prompt(cfg.system_prompt_file) if cfg.system_prompt_file else cfg.role
    )
    system = _render_prompt_template(system_template, template_vars or {})
    if extra_context:
        system = f"{system}\n\n## Context\n{extra_context}"

    # Get tool descriptions in ReAct format
    tool_descriptions = tool_registry.list_react_descriptions(allowed_tools)
    system = _build_react_system_prompt(system, tool_descriptions)

    # Build the conversation
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    # Try each endpoint in the fallback chain
    chain = [cfg.primary, cfg.fallback, cfg.fallback_2]
    last_err: Exception | None = None

    for endpoint in chain:
        if endpoint is None:
            continue
        try:
            result = _react_loop_with_endpoint(
                agent_name, endpoint, messages, cfg, tool_registry, tool_ctx,
                conversation_id, json_mode,
            )
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            from pathlib import Path
            import time as _time
            log_path = Path("logs/router.log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"[{_time.strftime('%Y-%m-%dT%H:%M:%S')}] "
                    f"agent={agent_name} model={endpoint.display_name} "
                    f"react_loop failed: {type(e).__name__}: {e}\n"
                )
            continue

    # All endpoints failed
    if cfg.allow_mock:
        from llm.router import _mock_response
        return _mock_response(agent_name, prompt, cfg.role)
    raise RuntimeError(
        f"agent {agent_name}: all providers failed in react_loop. last_err={last_err}"
    )


def _react_loop_with_endpoint(
    agent_name: str,
    endpoint: ModelEndpoint,
    messages: list[dict[str, str]],
    cfg: AgentConfig,
    tool_registry: Any,
    tool_ctx: ToolContext,
    conversation_id: str | None = None,
    json_mode: bool = False,
) -> str:
    """Run the ReAct loop with a single endpoint."""
    import litellm

    kwargs: dict[str, Any] = {
        "model": endpoint.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "num_retries": endpoint.num_retries,
        "request_timeout": endpoint.request_timeout,
        "stream": False,  # non-streaming for tool loop (need full response)
    }
    if endpoint.api_base:
        kwargs["api_base"] = endpoint.api_base
    if endpoint.api_key:
        kwargs["api_key"] = endpoint.api_key
        
    # WebAI2API integration: pass conversationId and json_mode via extra_body
    if endpoint.api_base and (conversation_id or json_mode):
        extra_body = {}
        if conversation_id:
            extra_body["conversationId"] = conversation_id
        if json_mode:
            extra_body["json_mode"] = True
        kwargs["extra_body"] = extra_body

    iteration = 0
    all_tool_results: list[str] = []

    while iteration < MAX_TOOL_ITERATIONS:
        iteration += 1

        # Call the model
        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content or ""

        # Check for blocked
        blocked_m = BLOCKED_RE.search(content)
        if blocked_m:
            return content  # return as-is, write_output will handle <blocked>

        # Check for done
        done_m = DONE_RE.search(content)
        if done_m:
            return _extract_final_answer(content)

        # Extract tool calls
        tool_calls = _extract_tool_calls(content)

        if not tool_calls:
            # No tool calls — this is the final answer
            return _extract_final_answer(content)

        # Execute tool calls and build results
        tool_results_text = []
        for call in tool_calls:
            tool_name = call.get("name", "")
            arguments = call.get("arguments", {})

            # Execute via registry
            result: ToolResult = tool_registry.execute(tool_name, tool_ctx, **arguments)

            # Format result for the model
            tool_results_text.append(
                f"<tool_result>\n"
                f"Tool: {tool_name}\n"
                f"Arguments: {json.dumps(arguments)}\n"
                f"Success: {result.success}\n"
                f"Output:\n{result.to_llm_text()}\n"
                f"</tool_result>"
            )

            # Log to myforge state
            try:
                tool_ctx.state.append_log(
                    f"tool_call: agent={agent_name} tool={tool_name} "
                    f"success={result.success} iter={iteration}"
                )
            except Exception:
                pass

        results_block = "\n".join(tool_results_text)
        all_tool_results.append(results_block)

        # Append the model's tool-call response + results to conversation
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": results_block})

        # Update messages for next call
        kwargs["messages"] = messages

    # Max iterations reached — return whatever we have
    return (
        "<done>\n"
        f"Reached max tool iterations ({MAX_TOOL_ITERATIONS}). "
        f"Last tool results may be incomplete.\n"
        "</done>\n\n"
        + (all_tool_results[-1] if all_tool_results else "")
    )
