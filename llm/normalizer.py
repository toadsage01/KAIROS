# llm/normalizer.py
"""
Output normalizer — uses Groq + instructor to parse free-form LLM output
into structured data when the primary parser fails.

If GROQ_API_KEY is set, uses Groq (llama-3.3-70b-versatile) with
instructor for structured JSON output. If not, falls back to legacy
regex parsing.

Exports:
  - normalize_plan(raw_text) → Plan  (for thinker output)
  - normalize_coder_output(raw_text, task, task_id) → list[FileBlock]  (for coder output)
"""
import os
import re
from typing import Any

try:
    import instructor
    _HAS_INSTRUCTOR = True
except ImportError:
    instructor = None  # type: ignore
    _HAS_INSTRUCTOR = False

try:
    from groq import Groq
    _HAS_GROQ = True
except ImportError:
    Groq = None  # type: ignore
    _HAS_GROQ = False

try:
    from pydantic import BaseModel, Field
    _HAS_PYDANTIC = True
except ImportError:
    BaseModel = object  # type: ignore
    Field = lambda **kw: None  # type: ignore
    _HAS_PYDANTIC = False


# ---------- schemas ----------
if _HAS_PYDANTIC:

    class TaskItem(BaseModel):
        id: str
        title: str
        description: str
        needs_research: bool = False
        files: str = ""
        acceptance_criteria: str = ""

    class Plan(BaseModel):
        tasks: list[TaskItem]
        is_blocked: bool = False
        blocked_reason: str = ""

    class CodeBlock(BaseModel):
        path: str
        content: str
        language: str = "python"
        action: str = "modify"  # create | modify | delete

    class CoderOutput(BaseModel):
        blocks: list[CodeBlock]
        is_blocked: bool = False
        blocked_reason: str = ""

else:
    # Fallbacks if pydantic not available
    Plan = dict  # type: ignore
    CoderOutput = dict  # type: ignore


# ---------- Groq client setup ----------
_groq_client = None
_groq_norm = None

if _HAS_INSTRUCTOR and _HAS_GROQ and os.environ.get("GROQ_API_KEY"):
    try:
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
        _groq_norm = instructor.from_groq(
            _groq_client,
            mode=instructor.Mode.JSON,
        )
    except Exception:
        _groq_norm = None


# ---------- plan normalizer ----------
def normalize_plan(raw_text: str, max_retries: int = 3) -> Plan:
    """Normalize thinker output into a Plan schema."""
    if _groq_norm is None or not _HAS_PYDANTIC:
        return _legacy_parse_plan(raw_text)
    return _groq_norm.chat.completions.create(
        model="llama-3.3-70b-versatile",
        response_model=Plan,
        max_retries=max_retries,
        messages=[
            {"role": "system", "content": (
                "Convert a planner agent's free-text output into the Plan schema. "
                "Preserve every task detail exactly. If the planner emitted <blocked>, "
                "set is_blocked=true and copy the reason verbatim. "
                "NEVER omit required fields — if a field is missing from the source, "
                "infer it from context (e.g. acceptance_criteria from the goal)."
            )},
            {"role": "user", "content": raw_text[:30000]},
        ],
    )


def _legacy_parse_plan(raw_text: str) -> Plan:
    """Fallback regex parser when Groq/instructor not available."""
    if not _HAS_PYDANTIC:
        return {"tasks": [], "is_blocked": False}  # type: ignore

    tasks = []
    task_blocks = re.split(r"^TASK\s+(T\d+)", raw_text, flags=re.MULTILINE)
    for i in range(1, len(task_blocks), 2):
        task_id = task_blocks[i]
        block = task_blocks[i + 1]
        task = TaskItem(
            id=task_id,
            title=_extract_field(block, "title"),
            description=_extract_field(block, "description"),
            needs_research=_extract_field(block, "needs_research").lower() == "true",
            files=_extract_field(block, "files"),
            acceptance_criteria=_extract_field(block, "acceptance_criteria"),
        )
        if task.title:
            tasks.append(task)

    blocked = "<blocked>" in raw_text.lower()
    blocked_reason = ""
    if blocked:
        m = re.search(r"<blocked>\s*(.*?)\s*</blocked>", raw_text, re.DOTALL | re.IGNORECASE)
        if m:
            blocked_reason = m.group(1).strip()

    return Plan(tasks=tasks, is_blocked=blocked, blocked_reason=blocked_reason)


def _extract_field(block: str, field: str) -> str:
    """Extract a 'field: value' pair from a text block."""
    pattern = rf"^{field}:\s*(.*?)(?=\n\w+:|\Z)"
    m = re.search(pattern, block, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip().strip("\"'") if m else ""


# ---------- preprocessing helpers ----------
def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from DeepSeek and other reasoning models.
    
    DeepSeek's "thinking" mode wraps reasoning in <think> tags. These pollute
    the output and break parsers. Strip them before any processing.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)


def strip_prose_around_code(text: str) -> str:
    """Remove conversational prose before/after code blocks.
    
    SOTA models via web bridge often add "Here's the code:" before code blocks
    and "Let me know if you need changes!" after. This strips everything that
    isn't inside a fenced code block.
    """
    # Find all code blocks
    blocks = list(re.finditer(r"```[a-zA-Z0-9_+-]*[^\n`]*\n.*?\n```", text, re.DOTALL))
    if not blocks:
        return text  # no code blocks — return as-is

    # Keep only the code blocks, joined by newlines
    cleaned = "\n\n".join(m.group(0) for m in blocks)
    return cleaned


# ---------- coder output normalizer ----------
def normalize_coder_output(
    raw_text: str,
    task: dict[str, Any] | None = None,
    task_id: str = "",
    max_retries: int = 3,
) -> list:
    """Normalize coder output into a list of FileBlock objects.

    This is the fallback when parse_coder_output() from core/parser.py
    fails to extract any code blocks. Uses Groq + instructor to parse
    free-form text into structured CodeBlock objects.

    Preprocessing steps (before parsing):
      1. Strip <think> tags (DeepSeek reasoning mode)
      2. Strip conversational prose around code blocks
      3. Check for <blocked> tag

    Returns:
        list[FileBlock] — can be empty if the model output is truly empty
        or if the model emitted <blocked>.
    """
    # Step 1: Strip <think> tags
    raw_text = strip_think_tags(raw_text)

    # Step 2: Check for blocked tag
    blocked_m = re.search(
        r"<blocked>\s*(.*?)\s*</blocked>",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    if blocked_m:
        # Model declined — return empty list, caller should handle
        return []

    # Step 3: If there are code blocks but parser missed them, try stripping prose
    # This handles cases like "Here's the code:\n```python path=foo.py\n...\n```"
    # where the parser got confused by leading prose
    has_code_block = bool(re.search(r"```[a-zA-Z0-9_+-]*", raw_text))
    if has_code_block:
        cleaned = strip_prose_around_code(raw_text)
        from core.parser import parse_coder_output
        blocks = parse_coder_output(cleaned, task=task, task_id=task_id)
        if blocks:
            return blocks

    # Step 4: Try the original parser on the <think>-stripped text
    from core.parser import parse_coder_output
    blocks = parse_coder_output(raw_text, task=task, task_id=task_id)
    if blocks:
        return blocks

    # Step 5: Use Groq + instructor as last resort
    if _groq_norm is not None and _HAS_PYDANTIC:
        try:
            result = _groq_norm.chat.completions.create(
                model="llama-3.3-70b-versatile",
                response_model=CoderOutput,
                max_retries=max_retries,
                messages=[
                    {"role": "system", "content": (
                        "Extract code blocks from a coder agent's output. "
                        "Each block must have: path (file path), content (full file "
                        "content), language (python/js/etc), action (create/modify/delete). "
                        "If the output contains <blocked>, set is_blocked=true. "
                        "Preserve ALL code exactly — do not truncate or summarize."
                    )},
                    {"role": "user", "content": raw_text[:50000]},
                ],
            )
            # Convert CoderOutput to FileBlock list
            from core.parser import FileBlock
            blocks = []
            for blk in result.blocks:
                blocks.append(FileBlock(
                    path=blk.path,
                    content=blk.content,
                    language=blk.language,
                    action=blk.action,
                ))
            return blocks
        except Exception:
            pass  # fall through to empty return

    # All normalization attempts failed — return empty list
    return []
