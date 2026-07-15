"""
Model brand colors for Kairos TUI.

Each model gets its brand color. When a model is active, its name and
status indicator appear in this color in the TUI.

Textual uses CSS-like color values. We support both hex and ANSI names
so it works in any terminal (256-color compatible).
"""

# Model → (hex color, ANSI name for terminals that don't support hex)
MODEL_COLORS = {
    # Anthropic (Claude) — orange/coral
    "claude-sonnet-5":   "#D97757",
    "claude-opus-5":     "#C97147",
    "claude-haiku-5":    "#E89070",
    "claude-auto":       "#D97757",

    # OpenAI (GPT) — teal/green
    "gpt-thinking":      "#10A37F",
    "gpt-instant":       "#10A37F",
    "gpt-pro":           "#10A37F",

    # DeepSeek — blue
    "deepseek":          "#4D6BFE",
    "deepseek-thinking": "#4D6BFE",
    "deepseek-search":   "#4D6BFE",

    # Google (Gemini) — Google blue
    "gemini-3.1-pro":    "#4285F4",
    "gemini-3.1-flash":  "#4285F4",
    "gemini-3.1-flash-thinking": "#4285F4",

    # Z.ai (GLM) — purple
    "glm-5.2":           "#6F42E1",
    "glm-5.1":           "#6F42E1",
    "glm-5":             "#6F42E1",
    "glm-4.6":           "#6F42E1",
    "glm-4.5":           "#6F42E1",

    # Groq — red
    "groq":              "#F55036",
    "llama-3.3-70b":     "#F55036",

    # Mock — gray
    "mock":              "#6B7280",
}

# Status colors (independent of model)
STATUS_COLORS = {
    "running":  "yellow",
    "paused":   "yellow",
    "done":     "green",
    "error":    "red",
    "idle":     "cyan",
}

# Agent status icons
AGENT_ICONS = {
    "pending":   "○",
    "running":   "●",
    "done":      "✓",
    "approved":  "✓",
    "rejected":  "✗",
    "error":     "✗",
    "blocked":   "⚠",
    "skipped":   "—",
}


def get_model_color(model_name: str) -> str:
    """Get the brand color for a model.

    Tries exact match first, then prefix match, then default gray.
    """
    if not model_name:
        return "#6B7280"

    # Strip provider prefix (openai/claude-sonnet-5 → claude-sonnet-5)
    clean = model_name.split("/")[-1] if "/" in model_name else model_name

    # Try exact match
    if clean in MODEL_COLORS:
        return MODEL_COLORS[clean]

    # Try prefix match (e.g., "claude-sonnet-5@localhost" → "claude-sonnet-5")
    for key, color in MODEL_COLORS.items():
        if clean.startswith(key):
            return color

    # Try partial match
    for key, color in MODEL_COLORS.items():
        if key in clean:
            return color

    return "#6B7280"  # default gray


def get_status_color(status: str) -> str:
    """Get color for a run status."""
    return STATUS_COLORS.get(status, "white")


def get_agent_icon(status: str) -> str:
    """Get the icon for an agent status."""
    return AGENT_ICONS.get(status, "○")


def format_model_display(model_name: str) -> str:
    """Format a model name for display.

    Strips provider prefix and @localhost suffix.
    Example: "openai/claude-sonnet-5@localhost" → "Claude Sonnet 5"
    """
    if not model_name:
        return "Unknown"

    # Strip prefix
    clean = model_name.split("/")[-1] if "/" in model_name else model_name

    # Strip @localhost
    clean = clean.split("@")[0] if "@" in clean else clean

    # prettify
    clean = clean.replace("-", " ").replace("_", " ")

    # Capitalize known names
    replacements = {
        "claude sonnet 5": "Claude Sonnet 5",
        "claude opus 5": "Claude Opus 5",
        "claude haiku 5": "Claude Haiku 5",
        "claude auto": "Claude Auto",
        "gpt thinking": "GPT-4o Thinking",
        "gpt instant": "GPT-4o Instant",
        "gpt pro": "GPT-4o Pro",
        "deepseek thinking": "DeepSeek Thinking",
        "deepseek search": "DeepSeek Search",
        "deepseek": "DeepSeek",
        "gemini 3.1 pro": "Gemini Pro",
        "gemini 3.1 flash thinking": "Gemini Flash Thinking",
        "gemini 3.1 flash": "Gemini Flash",
        "glm 5.2": "GLM-5.2",
        "glm 5.1": "GLM-5.1",
        "glm 5": "GLM-5",
        "glm 4.6": "GLM-4.6",
        "glm 4.5": "GLM-4.5",
        "llama 3.3 70b versatile": "Groq Llama 3.3",
        "mock": "Mock (fallback)",
    }

    lower = clean.lower()
    if lower in replacements:
        return replacements[lower]

    # Title case fallback
    return clean.title()
