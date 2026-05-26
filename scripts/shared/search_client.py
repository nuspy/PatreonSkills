"""Multi-source search client for competitor intelligence and trend research.

Supports:
- Google Custom Search API (requires API key + CX)
- Bing Web Search API (requires API key)
- DuckDuckGo (no API key needed, rate-limited)
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote_plus

import httpx


class SearchClient:
    """Multi-source web search client."""

    def __init__(self, config: dict):
        self.google_key = config.get("google_search_api_key", "")
        self.google_cx = config.get("google_search_cx", "")
        self.bing_key = config.get("bing_search_api_key", "")

    async def search(
        self,
        query: str,
        num_results: int = 10,
        source: str = "auto",
    ) -> list[dict]:
        """Search the web for the given query.

        Args:
            query: Search query string
            num_results: Number of results to return
            source: 'google', 'bing', 'duckduckgo', or 'auto' (tries in order)

        Returns:
            List of result dicts with title, url, snippet
        """
        if source == "auto":
            if self.google_key and self.google_cx:
                source = "google"
            elif self.bing_key:
                source = "bing"
            else:
                source = "duckduckgo"

        if source == "google":
            return await self._google_search(query, num_results)
        elif source == "bing":
            return await self._bing_search(query, num_results)
        else:
            return await self._duckduckgo_search(query, num_results)

    async def _google_search(self, query: str, num: int) -> list[dict]:
        """Google Custom Search API."""
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": self.google_key,
            "cx": self.google_cx,
            "q": query,
            "num": min(num, 10),
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        return [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source": "google",
            }
            for item in data.get("items", [])
        ]

    async def _bing_search(self, query: str, num: int) -> list[dict]:
        """Microsoft Bing Web Search API."""
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self.bing_key}
        params = {"q": query, "count": min(num, 50), "mkt": "en-US"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

        return [
            {
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "source": "bing",
            }
            for item in data.get("webPages", {}).get("value", [])
        ]

    async def _duckduckgo_search(self, query: str, num: int) -> list[dict]:
        """DuckDuckGo Instant Answer API (no auth required, limited results)."""
        url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return []
            data = response.json()

        results = []

        # Abstract result
        if data.get("AbstractURL") and data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", query),
                "url": data["AbstractURL"],
                "snippet": data["AbstractText"][:300],
                "source": "duckduckgo",
            })

        # Related topics
        for topic in data.get("RelatedTopics", [])[:num - 1]:
            if isinstance(topic, dict) and topic.get("FirstURL"):
                results.append({
                    "title": topic.get("Text", "")[:100],
                    "url": topic["FirstURL"],
                    "snippet": topic.get("Text", "")[:300],
                    "source": "duckduckgo",
                })

        return results[:num]

    async def search_patreon_creators(
        self, keywords: list[str], num_per_query: int = 5
    ) -> list[dict]:
        """Search for Patreon creators in a niche."""
        results = []
        for keyword in keywords:
            query = f"site:patreon.com {keyword} creator"
            items = await self.search(query, num_per_query)
            for item in items:
                if "patreon.com/" in item.get("url", ""):
                    item["keyword"] = keyword
                    results.append(item)
            await asyncio.sleep(0.5)  # Rate limiting
        return results
