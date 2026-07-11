# llm/normalizer.py
import os, instructor
from openai import OpenAI
from groq import Groq
from llm.schemas import Plan

_groq_norm = instructor.from_groq(
    Groq(api_key=os.environ.get("GROQ_API_KEY", "")),
    mode=instructor.Mode.JSON,
) if os.environ.get("GROQ_API_KEY") else None

def normalize_plan(raw_text: str, max_retries: int = 3) -> Plan:
    if _groq_norm is None:
        # Fallback: regex parse + manual validation
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