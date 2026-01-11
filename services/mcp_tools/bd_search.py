from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

Json = Dict[str, Any]


def _tokenize(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _load_pages() -> List[Json]:
    """Load curated Overheid pages dataset (demo-safe, deterministic)."""
    here = os.path.dirname(__file__)
    path = os.path.join(here, "data", "bd_pages.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pages = data.get("pages", [])
    if not isinstance(pages, list):
        return []
    return pages


def _score_page(tokens: List[str], title: str, snippet: str, keywords: List[str]) -> int:
    """Deterministic scoring: title match is weighted heavier than snippet."""
    t = (title or "").lower()
    s = (snippet or "").lower()
    k = " ".join((keywords or [])).lower()

    score = 0
    for tok in tokens:
        if tok in t:
            score += 4
        elif tok in k:
            score += 3
        elif tok in s:
            score += 1
    return score


def bd_search(query: str, k: int = 5) -> Json:
    """
    Demo MCP tool: search Overheid.nl content from a curated local dataset.

    Args:
      query: free-text query
      k: number of results

    Returns:
      { "items": [ { "title": str, "url": str, "snippet": str } ... ] }
    """
    pages = _load_pages()
    q = (query or "").strip()
    tokens = _tokenize(q)

    scored: List[Tuple[int, str, Json]] = []
    for p in pages:
        title = str(p.get("title", ""))
        url = str(p.get("url", ""))
        snippet = str(p.get("snippet", ""))
        keywords = p.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        score = _score_page(tokens, title, snippet, keywords)

        scored.append((score, title.lower(), {"title": title, "url": url, "snippet": snippet}))

    # Sort: highest score first, then title for stability
    scored.sort(key=lambda x: (-x[0], x[1]))

    # Filter low-score results unless query is empty
    items = [item for (score, _, item) in scored if score > 0]

    # If nothing matched, return a stable "general" set
    if not items:
        items = [{"title": str(p.get("title", "")), "url": str(p.get("url", "")), "snippet": str(p.get("snippet", ""))} for p in pages]

    return {"items": items[: max(1, int(k or 5))]}
