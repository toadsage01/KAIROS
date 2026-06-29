"""Researcher — runs when thinker flags a task with needs_research=true.

Flow (still ONE LLM call):
  1. Build a search query from the task title + description
  2. Call tools.web.search_and_extract() to fetch top-N web results
  3. Pass the fetched content as bounded context to the LLM
  4. The LLM synthesizes structured research notes
  5. Write to state/research/{task_id}.md

Without TAVILY_API_KEY, step 2 returns [] and the LLM still produces
notes from its own knowledge (clearly labeled as such).
"""
from __future__ import annotations

from agents.base import AgentContext, BaseAgent
from tools.web import search_and_extract


class ResearcherAgent(BaseAgent):
    name = "researcher"

    def build_prompt(self, ctx: AgentContext) -> str:
        task = ctx.task or {}
        title = task.get("title", "")
        desc = task.get("description", "")
        # 1. Build a search query
        query = f"{title} {desc}".strip() or title
        # 2. Fetch web results (best-effort; [] if no TAVILY_API_KEY)
        try:
            results = search_and_extract(query, max_results=3)
        except Exception as e:  # noqa: BLE001
            results = []
            self.state.append_log(f"researcher web search failed: {e}")

        # 3. Build prompt with fetched content
        parts = [
            f"Produce research notes for task {ctx.task_id}.",
            f"\nTitle: {title}",
            f"Description: {desc}",
        ]
        if results:
            parts.append(f"\n## Web search results for: \"{query}\"")
            for i, r in enumerate(results, 1):
                parts.append(f"\n### Source {i}: {r.get('title', '(untitled)')}")
                if r.get("url"):
                    parts.append(f"URL: {r['url']}")
                if r.get("content"):
                    parts.append(f"Snippet: {r['content'][:600]}")
                if r.get("full_text"):
                    parts.append(f"\nExtracted content (truncated):\n{r['full_text'][:1500]}")
            parts.append(
                "\nSynthesize the above into the research notes format from your "
                "system prompt. Cite URLs in [Findings]. If sources conflict, note it."
            )
        else:
            parts.append(
                "\n(no web results available — either TAVILY_API_KEY is unset or "
                "search returned nothing. Produce notes from your own knowledge, "
                "and explicitly say 'no external sources' in the Summary.)"
            )
        return "\n".join(parts)

    def write_output(self, ctx: AgentContext, model_output: str) -> str:
        path = self.state.write_md(ctx.task_id, model_output, subdir="research")
        return str(path)
