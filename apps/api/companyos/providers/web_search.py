from dataclasses import dataclass

import httpx


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class WebSearchUnavailable(Exception):
    pass


async def tavily_search(api_key: str, query: str, max_results: int = 5) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": max_results},
        )
    if response.status_code >= 400:
        raise WebSearchUnavailable(f"Web search failed with status {response.status_code}")
    return [
        SearchResult(
            title=item.get("title", ""), url=item.get("url", ""), snippet=item.get("content", "")[:800]
        )
        for item in response.json().get("results", [])
    ]
