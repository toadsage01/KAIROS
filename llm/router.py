"""
LLM Router — LiteLLM wrapper with fallback chain + mock provider + web bridges.

Design rules (per project spec):
  - Each agent = ONE LLM call with bounded input.
  - Fallback chain per agent: try primary, then fallback, then fallback_2.
  - If all fail AND allow_mock=true, return a deterministic mock so dev
    never blocks on a missing API key.
  - Token cost is predictable because there is no chatter — exactly one
    successful call per agent per invocation.

Web Bridge Support (Kairos extension):
  Each model slot in agents.yaml can be either a string (legacy) or a
  dict with api_base + api_key. This lets you mix cloud APIs and web
  bridges (WebAI2API, intense-rp-next, etc.) in the same fallback chain.

  Example:
    fallback_2:
      model: "openai/gpt-pro"
      api_base: "http://localhost:3006/v1"
      api_key: "sk-kairos-master-2026"
      request_timeout: 120
      num_retries: 0

The router is the ONLY place that knows about LiteLLM. Agents import
`route()` and get back a string.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

# Lazy import — litellm is heavy and we want graceful failure if missing
try:
    import litellm  # type: ignore
    _HAS_LITELLM = True
except ImportError:
    litellm = None  # type: ignore
    _HAS_LITELLM = False


# ---------- model endpoint ----------
@dataclass
class ModelEndpoint:
    """A single model endpoint. May be a cloud API (model only) or a web
    bridge (model + api_base + api_key)."""
    model: str
    api_base: str | None = None
    api_key: str | None = None
    request_timeout: int = 60
    num_retries: int = 0  # our route() does its own fallback; let LiteLLM fail fast

    @classmethod
    def parse(cls, spec: str | dict | None) -> "ModelEndpoint | None":
        """Parse a model slot from YAML. Accepts:
          - None → None
          - "groq/llama-3.3-70b" → ModelEndpoint(model="groq/llama-3.3-70b")
          - {model: "openai/gpt-pro", api_base: "...", api_key: "..."} → full endpoint
        """
        if spec is None:
            return None
        if isinstance(spec, str):
            return cls(model=spec)
        if isinstance(spec, dict):
            return cls(
                model=spec.get("model", ""),
                api_base=spec.get("api_base"),
                api_key=spec.get("api_key"),
                request_timeout=int(spec.get("request_timeout", 60)),
                num_retries=int(spec.get("num_retries", 0)),
            )
        raise ValueError(f"invalid model spec: {spec!r}")

    @property
    def display_name(self) -> str:
        """Short name for logs — includes api_base host if web bridge."""
        if self.api_base:
            from urllib.parse import urlparse
            host = urlparse(self.api_base).hostname or self.api_base
            return f"{self.model}@{host}"
        return self.model


@dataclass
class AgentConfig:
    name: str
    role: str
    primary: ModelEndpoint
    fallback: ModelEndpoint | None = None
    fallback_2: ModelEndpoint | None = None
    system_prompt_file: str | None = None
    temperature: float = 0.2
    max_tokens: int = 2048
    allow_mock: bool = True
    needs_tools: list[str] | None = None
    # Batch 3: tool support
    use_tools: bool = False
    allowed_tools: list[str] = field(default_factory=list)
    # Response validation: minimum acceptable response length
    # If the model returns fewer chars than this, treat as failure and
    # try the next fallback. Prevents garbled/truncated SOTA output from
    # being accepted as "success" when it's actually garbage.
    min_response_length: int = 50


def load_agents(path: str = "config/agents.yaml") -> dict[str, AgentConfig]:
    with open(path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    out: dict[str, AgentConfig] = {}
    for name, a in spec.get("agents", {}).items():
        model = a.get("model", {})
        primary = ModelEndpoint.parse(model.get("primary"))
        if primary is None:
            raise ValueError(f"agent {name} has no primary model")
        out[name] = AgentConfig(
            name=name,
            role=a.get("role", ""),
            primary=primary,
            fallback=ModelEndpoint.parse(model.get("fallback")),
            fallback_2=ModelEndpoint.parse(model.get("fallback_2")),
            system_prompt_file=a.get("system_prompt_file"),
            temperature=a.get("temperature", 0.2),
            max_tokens=a.get("max_tokens", 2048),
            allow_mock=a.get("allow_mock", True),
            needs_tools=a.get("needs_tools"),
            use_tools=a.get("use_tools", False),
            allowed_tools=a.get("allowed_tools", []),
            min_response_length=a.get("min_response_length", 50),
        )
    return out


def _load_prompt(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _render_prompt_template(template: str, variables: dict[str, Any]) -> str:
    """Render a system prompt template before sending it to the model.

    Uses Jinja2 if available, otherwise falls back to simple {{ var }} replacement.
    """
    if not template or "{{" not in template:
        return template
    try:
        from jinja2 import Environment
        env = Environment(autoescape=False)
        return env.from_string(template).render(**variables)
    except ImportError:
        # Fallback: simple string replacement
        rendered = template
        for key, value in variables.items():
            rendered = rendered.replace("{{ " + key + " }}", str(value))
            rendered = rendered.replace("{{" + key + "}}", str(value))
        return rendered


def _mock_response(agent: str, prompt: str, role: str) -> str:
    """Deterministic mock — same prompt always yields same output.

    This is the safety net that lets the DAG run end-to-end with zero
    API keys configured. Production runs will use real models.
    """
    h = hashlib.sha256(f"{agent}|{prompt}".encode()).hexdigest()[:8]
    if agent == "thinker":
        # Format that works with BOTH parser variants:
        #   - Codex parser: splits on "^TASK\s+(T\d+)" — matches "TASK T1"
        #   - Original parser: splits on "^## Task\s+" — matches "## Task T1"
        # Solution: output "## Task T1" which the original parser handles,
        # AND include "TASK T1" format that the Codex parser handles.
        # The Codex parser runs first (if present), so we use its format.
        # If only the original parser is present, it won't match — but the
        # normalizer fallback (normalize_plan) will handle it.
        #
        # KEY: every field MUST have a non-empty value (parser bug: empty
        # fields swallow the next field due to \s* consuming newlines).
        return (
            "# Plan\n\n"
            "Generated by mock thinker (configure a real model in config/agents.yaml).\n\n"
            "TASK T1\n"
            "id: T1\ntitle: Implement the goal\ndescription: First task — researcher will try to web-ground this.\n"
            "needs_research: true\nfiles: main.py\nacceptance_criteria: Goal is implemented and tested.\n\n"
            "TASK T2\n"
            "id: T2\ntitle: Add tests\ndescription: Write tests for the implementation.\n"
            f"needs_research: false\nfiles: test_main.py\nacceptance_criteria: Tests pass.\n"
        )
    if agent == "coder":
        return (
            f"// mock coder output (hash {h})\n"
            f"// role: {role}\n\n"
            "```python path=src/hello.py\n"
            "def hello():\n"
            "    return 'hello from myforge'\n"
            "```\n\n"
            "```python path=tests/test_hello.py\n"
            "from src.hello import hello\n"
            "def test_hello():\n"
            "    assert hello() == 'hello from myforge'\n"
            "```\n"
        )
    if agent == "reviewer":
        return "STATUS: approved\n\nNo defects found. (mock reviewer)\n"
    if agent == "bugfixer":
        return "// mock bugfixer: applied reviewer notes (no-op)\n"
    if agent == "researcher":
        return (
            f"# Research: {h}\n\n"
            "## Summary\n\n"
            "(mock researcher) No external sources — TAVILY_API_KEY not set or "
            "no results returned. Notes below are from the model's own knowledge.\n\n"
            "## Findings\n\n"
            "- No web sources were available for this task.\n\n"
            "## Recommendations for the coder\n\n"
            "- Proceed using existing repo context.\n"
            "- If the task genuinely requires external info, set TAVILY_API_KEY "
            "and re-run.\n"
        )
    return f"[mock {agent}] {role}"


def _validate_response(text: str, endpoint: ModelEndpoint) -> str:
    """Catch HTML/garbage responses from web bridges before they pollute state."""
    if not text or not text.strip():
        raise RuntimeError(f"empty response from {endpoint.display_name}")
    lower = text.lower()[:500]
    if "<html" in lower or "<!doctype" in lower:
        raise RuntimeError(
            f"HTML response from {endpoint.display_name} — likely Cloudflare "
            f"block or session expiry. First 200 chars: {text[:200]!r}"
        )
    if len(text) > 100_000:
        raise RuntimeError(f"oversized response from {endpoint.display_name}")
    return text


def _call_litellm(endpoint: ModelEndpoint, system: str, prompt: str,
                  temperature: float, max_tokens: int) -> str:
    """Single LiteLLM call. Raises on failure.

    Passes api_base and api_key when set (web bridge mode). Cloud APIs
    (no api_base) use LiteLLM's default routing via env vars.
    """
    if not _HAS_LITELLM:
        raise RuntimeError("litellm not installed")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    kwargs: dict[str, Any] = {
        "model": endpoint.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "num_retries": endpoint.num_retries,
        "request_timeout": endpoint.request_timeout,
    }
    # Web bridge: pass api_base + api_key so LiteLLM hits our local proxy
    if endpoint.api_base:
        kwargs["api_base"] = endpoint.api_base
    if endpoint.api_key:
        kwargs["api_key"] = endpoint.api_key
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content  # type: ignore


def _log_fallback(agent: str, endpoint: ModelEndpoint, err: Exception,
                  next_label: str | None) -> None:
    """Append a fallback event to logs/router.log so users can see which
    model in the chain succeeded and which failed."""
    from pathlib import Path
    import time
    log_path = Path("logs/router.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    next_msg = f" -> trying {next_label}" if next_label else " -> no more fallbacks"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] "
            f"agent={agent} model={endpoint.display_name} failed: "
            f"{type(err).__name__}: {err}{next_msg}\n"
        )


def _log_success(agent: str, endpoint: ModelEndpoint, is_mock: bool) -> None:
    from pathlib import Path
    import time
    log_path = Path("logs/router.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kind = "MOCK" if is_mock else "LIVE"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] "
            f"agent={agent} model={endpoint.display_name} OK ({kind})\n"
        )


def _log_prompt_response(agent: str, endpoint: ModelEndpoint,
                          system: str, prompt: str, response: str) -> None:
    """Log the full prompt + response for debugging.

    One file per LLM call, saved to logs/prompts/.
    Filename: {timestamp}_{agent}_{model_slug}.txt

    This is essential for prompt engineering — you can't improve prompts
    you can't see. Read these files in VS Code to debug why the SOTA model
    returned conversational text instead of code blocks, etc.
    """
    from pathlib import Path
    import time
    log_dir = Path("logs/prompts")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    model_slug = endpoint.model.replace("/", "_").replace(":", "_")
    filename = f"{ts}_{agent}_{model_slug}.txt"
    filepath = log_dir / filename
    content = f"""=== AGENT: {agent} ===
=== MODEL: {endpoint.display_name} ===
=== TIMESTAMP: {time.strftime('%Y-%m-%dT%H:%M:%S')} ===

========== SYSTEM PROMPT ==========
{system}

========== USER PROMPT ==========
{prompt}

========== MODEL RESPONSE ==========
{response}

========== END ==========
"""
    filepath.write_text(content, encoding="utf-8")
    # Also log the filepath to router.log so it's discoverable
    log_path = Path("logs/router.log")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] "
            f"prompt_log: {filepath}\n"
        )


def route(agent_name: str, prompt: str,
          agents: dict[str, AgentConfig] | None = None,
          extra_context: str = "",
          template_vars: dict[str, Any] | None = None,
          conversation_id: str | None = None,
          json_mode: bool = False) -> str:
    """Run one agent. Returns the model's text output.

    Tries primary -> fallback -> fallback_2 -> mock (if allowed).
    Never raises (unless allow_mock=False and all providers fail).
    Logs every attempt to logs/router.log so fallback chains are auditable.

    Each endpoint may be a cloud API (model only) or a web bridge
    (model + api_base + api_key). The chain can mix both freely.

    Args:
        conversation_id: If set, passed to WebAI2API for session continuity.
        json_mode: If True, injects strict JSON output directive.
    """
    if agents is None:
        agents = load_agents()
    cfg = agents.get(agent_name)
    if cfg is None:
        raise KeyError(f"unknown agent: {agent_name}")

    system_template = (
        _load_prompt(cfg.system_prompt_file) if cfg.system_prompt_file else cfg.role
    )
    system = _render_prompt_template(system_template, template_vars or {})
    if extra_context:
        system = f"{system}\n\n## Context\n{extra_context}"

    chain: list[tuple[str, ModelEndpoint | None]] = [
        ("primary", cfg.primary),
        ("fallback", cfg.fallback),
        ("fallback_2", cfg.fallback_2),
    ]
    last_err: Exception | None = None
    for i, (label, endpoint) in enumerate(chain):
        if endpoint is None:
            continue
        try:
            out = _call_litellm(
                endpoint=endpoint,
                system=system,
                prompt=prompt,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                conversation_id=conversation_id,
                json_mode=json_mode,
            )
            # Response quality validation: check minimum length
            # If the response is too short, it's likely garbled/truncated
            # SOTA web bridges sometimes return 16-char garbage. Treat as
            # failure and try the next fallback.
            if len(out.strip()) < cfg.min_response_length:
                raise RuntimeError(
                    f"response too short ({len(out.strip())} chars, "
                    f"min={cfg.min_response_length}) — likely truncated/garbled. "
                    f"Output: {out[:100]!r}"
                )
            _log_success(agent_name, endpoint, is_mock=False)
            _log_prompt_response(agent_name, endpoint, system, prompt, out)
            return out
        except Exception as e:  # noqa: BLE001
            last_err = e
            next_label = chain[i + 1][0] if i + 1 < len(chain) else None
            _log_fallback(agent_name, endpoint, e, next_label)
            continue

    if cfg.allow_mock:
        _log_success(agent_name, ModelEndpoint(model="mock"), is_mock=True)
        return _mock_response(agent_name, prompt, cfg.role)
    raise RuntimeError(
        f"agent {agent_name}: all providers failed and mock disabled. last_err={last_err}"
    )
