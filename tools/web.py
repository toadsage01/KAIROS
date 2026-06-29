"""
Phase 4 — web tools. Tavily search + httpx + trafilatura extract.

Graceful degradation: if TAVILY_API_KEY is unset, tavily_search returns
empty results (the researcher will still produce notes from the LLM's
own knowledge). If trafilatura is missing, extract_text returns "".

This is what keeps the system runnable on free tiers without keys.
"""
from __future__ import annotations

import os

import httpx


def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via Tavily. Returns list of {title, url, content}.

    Without TAVILY_API_KEY, returns [] — callers should handle this.
    """
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return []
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": query,
                "max_results": max_results,
                "include_answer": True,
            },
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
        # Tavily returns an "answer" field + a "results" list
        answer = data.get("answer") or ""
        results = data.get("results", [])
        out: list[dict] = []
        if answer:
            out.append({"title": "(Tavily answer)", "url": "", "content": answer})
        for item in results:
            out.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", "")[:2000],
            })
        return out
    except Exception:
        return []


def extract_text(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and extract main-text content via trafilatura.

    Returns "" on any failure (missing lib, network error, non-HTML).
    Never raises — the researcher treats extraction as best-effort.
    """
    if not url:
        return ""
    try:
        import trafilatura  # type: ignore
    except ImportError:
        return ""
    try:
        html = httpx.get(url, timeout=10.0, follow_redirects=True).text
        text = trafilatura.extract(html) or ""
        return text[:max_chars]
    except Exception:
        return ""


def search_and_extract(query: str, max_results: int = 3) -> list[dict]:
    """Convenience: search + extract top-N URLs. Returns enriched results.

    Each result gets a 'full_text' field with extracted content (truncated).
    """
    results = tavily_search(query, max_results=max_results)
    for r in results:
        if r.get("url") and not r.get("full_text"):
            r["full_text"] = extract_text(r["url"], max_chars=3000)
    return results
