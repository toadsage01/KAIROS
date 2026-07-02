"""
Coder output parser.

Handles two fence formats:
  1. Explicit path:   ```python path=calculator.py
  2. Implicit path:   ```python  (path inferred from task context)

If a block has no path= header, the parser uses the task's `files` field.
If that's empty, it uses a heuristic: if the code looks like a test
(contains "test" or "unittest"), path = "test_<task_id>.py". Otherwise,
path = the first file mentioned in the task description, or "main.py".
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FileBlock:
    path: str
    content: str
    language: str
    action: str = "modify"


# Matches:  ```lang [path=relative/path] [action=create|modify|delete]
_FENCE_RE = re.compile(
    r"^```([a-zA-Z0-9_+-]*)([^\n`]*)\s*$",
    re.MULTILINE,
)

_FENCE_ATTR_RE = re.compile(
    r"\b(?P<key>path|action)=(?P<value>\"[^\"]+\"|'[^']+'|\S+)",
    re.IGNORECASE,
)

_BLOCKED_RE = re.compile(
    r"<blocked>\s*(?P<reason>.*?)\s*</blocked>",
    re.IGNORECASE | re.DOTALL,
)

_TRAILING_NON_CODE_MARKERS = (
    "# INPUT HANDLING AND VALIDATION ANALYSIS",
    "# Current Implementation Analysis",
    "# Recommended Enhancements",
    "# ANALYSIS",
    "# NOTES",
    "# EXPLANATION",
    "INPUT HANDLING AND VALIDATION ANALYSIS",
)


def _parse_fence_attrs(attrs: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _FENCE_ATTR_RE.finditer(attrs):
        value = m.group("value").strip().strip("\"'")
        out[m.group("key").lower()] = value
    return out


def extract_blocked(md: str) -> str | None:
    """Return a model's blocked reason, if it emitted a <blocked> tag."""
    m = _BLOCKED_RE.search(md)
    if not m:
        return None
    return m.group("reason").strip() or "agent declined without a reason"


def _infer_path(content: str, task: dict | None = None, task_id: str = "") -> str:
    """Infer a file path when the LLM didn't include path=."""
    # 1. Check task's files field
    if task and task.get("files"):
        files_str = str(task["files"]).strip().strip("\"'")
        if files_str:
            # Take the first file mentioned
            first = files_str.split(",")[0].strip().strip("\"'")
            if first:
                return first
    # 2. Check task text for an explicit file path.
    if task:
        task_text = " ".join(
            str(task.get(k, "")) for k in ("title", "description")
        )
        m = re.search(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|c|cpp|h)\b", task_text)
        if m:
            return m.group(0)
    # 3. Check if it looks like a test
    content_lower = content.lower()
    if "unittest" in content_lower or "pytest" in content_lower or "def test_" in content_lower:
        return f"test_{task_id.lower()}.py" if task_id else "test_generated.py"
    # 4. Check if content has a module docstring with filename hint
    first_line = content.strip().split("\n")[0]
    m = re.match(r'#\s*(?:file|path|filename):\s*(\S+)', first_line, re.IGNORECASE)
    if m:
        return m.group(1)
    # 5. Default
    return "main.py"


def _strip_trailing_non_code(content: str, language: str) -> str:
    """Remove common LLM analysis tails accidentally included in code fences."""
    lines = content.rstrip().splitlines()
    while lines and lines[-1].strip() == "EOF":
        lines.pop()

    if language.lower() not in {"py", "python"}:
        return "\n".join(lines).rstrip()

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if any(stripped.startswith(marker) for marker in _TRAILING_NON_CODE_MARKERS):
            return "\n".join(lines[:idx]).rstrip()
    return "\n".join(lines).rstrip()


def parse_coder_output(md: str, task: dict | None = None, task_id: str = "") -> list[FileBlock]:
    """Extract all fenced code blocks from coder/bugfixer markdown.

    Handles both explicit (path=) and implicit (no path) fences.
    Returns blocks in document order.
    """
    blocks: list[FileBlock] = []
    pos = 0

    while pos < len(md):
        m = _FENCE_RE.search(md, pos)
        if not m:
            break

        lang = m.group(1) or "python"
        attrs = _parse_fence_attrs(m.group(2) or "")
        path = attrs.get("path")
        action = attrs.get("action", "modify").lower()

        content_start = m.end()
        close_idx = md.find("\n```", content_start)
        if close_idx == -1:
            content = md[content_start:].lstrip("\n")
            pos = len(md)
        else:
            content = md[content_start:close_idx].lstrip("\n").rstrip()
            pos = close_idx + 4  # skip past the closing ```

        content = _strip_trailing_non_code(content, lang)

        # Skip empty blocks unless they explicitly delete a file.
        if not content.strip() and action != "delete":
            continue

        # Infer path if not provided
        if not path:
            path = _infer_path(content, task, task_id)

        blocks.append(FileBlock(path=path, content=content, language=lang, action=action))

    return blocks
