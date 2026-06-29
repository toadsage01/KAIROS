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


# Matches:  ```lang path=relative/path
_EXPLICIT_FENCE_RE = re.compile(
    r"^```([a-zA-Z0-9_+-]*)\s+path=(\S+)\s*$",
    re.MULTILINE,
)

# Matches:  ```lang  (no path=)
_IMPLICIT_FENCE_RE = re.compile(
    r"^```([a-zA-Z0-9_+-]*)\s*$",
    re.MULTILINE,
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
        # Try explicit fence first: ```lang path=file
        m_explicit = _EXPLICIT_FENCE_RE.search(md, pos)
        # Then implicit fence: ```lang (no path)
        m_implicit = _IMPLICIT_FENCE_RE.search(md, pos)

        # Pick whichever comes first
        candidates = []
        if m_explicit:
            candidates.append(("explicit", m_explicit))
        if m_implicit:
            candidates.append(("implicit", m_implicit))

        if not candidates:
            break

        # Sort by position, take the earliest
        candidates.sort(key=lambda x: x[1].start())
        kind, m = candidates[0]

        if kind == "explicit":
            lang = m.group(1) or "text"
            path = m.group(2)
        else:
            lang = m.group(1) or "python"
            path = None  # will infer below

        content_start = m.end()
        close_idx = md.find("\n```", content_start)
        if close_idx == -1:
            content = md[content_start:].lstrip("\n")
            pos = len(md)
        else:
            content = md[content_start:close_idx].lstrip("\n").rstrip()
            pos = close_idx + 4  # skip past the closing ```

        content = _strip_trailing_non_code(content, lang)

        # Skip empty blocks
        if not content.strip():
            continue

        # Infer path if not provided
        if not path:
            path = _infer_path(content, task, task_id)

        blocks.append(FileBlock(path=path, content=content, language=lang))

    return blocks
