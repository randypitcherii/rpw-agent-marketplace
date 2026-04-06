"""
Exa MCP Server — web search and content retrieval via the Exa API.

Provides tools for neural/keyword search, content crawling, and finding
similar pages. Uses the exa-py SDK with the EXA_API_KEY env var.
"""

import os
from typing import Optional

from exa_py import Exa
from fastmcp import FastMCP

mcp = FastMCP(
    "exa",
    instructions="Search the web and retrieve content using the Exa neural search API",
)


def _get_client() -> Exa:
    """Build Exa client using EXA_API_KEY from environment."""
    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        raise RuntimeError("EXA_API_KEY not set")
    return Exa(api_key=api_key)


@mcp.tool()
def exa_search(
    query: str,
    num_results: int = 10,
    use_autoprompt: bool = True,
    include_text: bool = False,
) -> str:
    """Search the web using Exa neural search.

    Args:
        query: Search query string.
        num_results: Number of results to return. Default: 10
        use_autoprompt: Let Exa optimize the query automatically. Default: True
        include_text: Include page text content in results. Default: False
    """
    try:
        client = _get_client()
        if include_text:
            results = client.search_and_contents(
                query,
                num_results=num_results,
                use_autoprompt=use_autoprompt,
                text=True,
            )
        else:
            results = client.search(
                query,
                num_results=num_results,
                use_autoprompt=use_autoprompt,
            )

        if not results.results:
            return "No results found."

        lines = []
        for i, r in enumerate(results.results, 1):
            lines.append(f"{i}. {r.title}")
            lines.append(f"   URL: {r.url}")
            if r.published_date:
                lines.append(f"   Published: {r.published_date}")
            if include_text and hasattr(r, "text") and r.text:
                preview = r.text[:500].strip()
                lines.append(f"   Content: {preview}...")
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as e:
        return f"Error searching with Exa: {e}"


@mcp.tool()
def exa_get_contents(
    urls: list[str],
    max_chars: Optional[int] = 2000,
) -> str:
    """Retrieve the text content of one or more URLs using Exa.

    Args:
        urls: List of URLs to fetch content from.
        max_chars: Maximum characters of text to return per URL. Default: 2000
    """
    try:
        client = _get_client()
        results = client.get_contents(urls, text=True)

        if not results.results:
            return "No content retrieved."

        lines = []
        for r in results.results:
            lines.append(f"## {r.title or r.url}")
            lines.append(f"URL: {r.url}")
            if hasattr(r, "text") and r.text:
                text = r.text[:max_chars].strip() if max_chars else r.text.strip()
                lines.append(f"\n{text}")
                if max_chars and len(r.text) > max_chars:
                    lines.append(f"\n[truncated — {len(r.text)} total chars]")
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as e:
        return f"Error fetching contents with Exa: {e}"


@mcp.tool()
def exa_find_similar(
    url: str,
    num_results: int = 10,
    include_text: bool = False,
) -> str:
    """Find pages similar to a given URL using Exa.

    Args:
        url: The reference URL to find similar pages for.
        num_results: Number of similar results to return. Default: 10
        include_text: Include page text content in results. Default: False
    """
    try:
        client = _get_client()
        if include_text:
            results = client.find_similar_and_contents(
                url,
                num_results=num_results,
                text=True,
            )
        else:
            results = client.find_similar(url, num_results=num_results)

        if not results.results:
            return "No similar pages found."

        lines = [f"Pages similar to {url}:\n"]
        for i, r in enumerate(results.results, 1):
            lines.append(f"{i}. {r.title}")
            lines.append(f"   URL: {r.url}")
            if r.published_date:
                lines.append(f"   Published: {r.published_date}")
            if include_text and hasattr(r, "text") and r.text:
                preview = r.text[:500].strip()
                lines.append(f"   Content: {preview}...")
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as e:
        return f"Error finding similar pages with Exa: {e}"


def main() -> None:
    """Run the Exa MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
