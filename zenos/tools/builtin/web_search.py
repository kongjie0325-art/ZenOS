"""Built-in tool: WebSearchTool.

Performs a web search and returns a list of result snippets.  The actual
search backend is pluggable — by default the tool uses DuckDuckGo's
lite HTML endpoint, but subclasses or callers can supply a custom
``search_fn`` for any provider (SerpAPI, Bing, Brave, ...).
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from zenos.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


def _default_duckduckgo_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """Scrape DuckDuckGo Lite for *query*.

    Returns a list of dicts with ``title``, ``url``, and ``snippet`` keys.
    This is intentionally lightweight -- no API key required -- but fragile
    against HTML changes.  For production use, provide a proper API-backed
    ``search_fn``.
    """
    url = (
        "https://lite.duckduckgo.com/lite/"
        f"?q={urllib.parse.quote_plus(query)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "ZenOS/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    results: List[Dict[str, str]] = []
    for match in re.finditer(
        r'<a[^>]*class="[^"]*result-link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    ):
        link_url = match.group(1)
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if link_url and title:
            results.append({"title": title, "url": link_url, "snippet": ""})

    return results[:num_results]


class WebSearchTool(BaseTool):
    """Search the web and return result snippets.

    Parameters:
        query: The search string.
        num_results: Maximum results to return (1-10).
    """

    name = "web_search"
    description = (
        "Search the web for information. Returns a list of results with "
        "title, URL, and snippet fields."
    )
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="Search query string.",
        ),
        ToolParameter(
            name="num_results",
            type="integer",
            description="Maximum number of results to return (1-10).",
            required=False,
            default=5,
        ),
    ]

    def __init__(self, search_fn: Optional[Callable[..., List[Dict[str, str]]]] = None):
        """Optionally inject a custom search function.

        Args:
            search_fn: Callable(query: str, num_results: int) -> list[dict].
        """
        self._search_fn = search_fn or _default_duckduckgo_search

    def execute(self, **kwargs: Any) -> ToolResult:
        query: str = kwargs["query"]
        num_results: int = kwargs.get("num_results", 5)

        if not query.strip():
            return ToolResult.fail(error="Search query must not be empty.")

        num_results = max(1, min(10, num_results))

        try:
            results = self._search_fn(query=query, num_results=num_results)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Web search failed")
            return ToolResult.fail(
                error=f"Search failed: {exc}",
                query=query,
            )

        return ToolResult.ok(
            content=results,
            query=query,
            result_count=len(results),
        )
