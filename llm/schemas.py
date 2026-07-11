# llm/schemas.py
from pydantic import BaseModel, field_validator

class Task(BaseModel):
    id: str
    title: str
    description: str
    depends_on: str = "none"
    acceptance_criteria: str
    needs_research: bool = False
    files: str = ""

    @field_validator("description", "acceptance_criteria")
    @classmethod
    def not_empty(cls, v):
        if not v.strip():
            raise ValueError("Field is required and cannot be empty")
        return v

    @field_validator("title")
    @classmethod
    def title_must_be_imperative(cls, v):
        if len(v.split()) > 15:
            raise ValueError(f"Title too long ({len(v.split())} words, max 15)")
        return v

class Plan(BaseModel):
    is_blocked: bool = False
    blocked_reason: str | None = None
    tasks: list[Task] = []

    @field_validator("blocked_reason")
    @classmethod
    def reject_path_excuses(cls, v):
        if v is None:
            return v
        bad = ["path", "file cannot", "cannot be determined", "not specified"]
        if any(p in v.lower() for p in bad):
            raise ValueError(
                "Block reason mentions missing paths/files — per Thinker rule 6 "
                "you must propose a new file path instead of blocking. Retry."
            )
        return v