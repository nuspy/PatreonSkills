"""RSS/Atom feed monitor for niche trend tracking.

Fetches and parses RSS/Atom feeds to track:
- Industry news and blog posts
- Competitor content updates
- Topic trends relevant to the creator's niche
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx


class RSSMonitor:
    """Async RSS feed fetcher and parser."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "RSSMonitor":
        self._client = httpx.AsyncClient(
            headers={"User-Agent": "patreon-creator-skill/1.0 (RSS monitor)"},
            follow_redirects=True,
            timeout=15.0,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def fetch_feed(self, url: str) -> dict:
        """Fetch and parse a single RSS/Atom feed.

        Args:
            url: RSS feed URL

        Returns:
            Dict with feed info and list of entries
        """
        import feedparser

        try:
            response = await self._client.get(url)
            response.raise_for_status()
            content = response.text
        except Exception as exc:
            return {"url": url, "error": str(exc), "entries": []}

        # feedparser is synchronous, run in thread pool
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, content)

        entries = []
        for entry in feed.entries[:20]:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                except Exception:
                    pass

            entries.append({
                "title": getattr(entry, "title", ""),
                "url": getattr(entry, "link", ""),
                "summary": getattr(entry, "summary", "")[:500],
                "published": published,
                "author": getattr(entry, "author", ""),
                "tags": [t.get("term", "") for t in getattr(entry, "tags", [])],
            })

        return {
            "url": url,
            "feed_title": getattr(feed.feed, "title", ""),
            "feed_description": getattr(feed.feed, "description", "")[:300],
            "entries": entries,
            "entry_count": len(entries),
        }

    async def fetch_multiple(
        self, urls: list[str], delay: float = 0.5
    ) -> list[dict]:
        """Fetch multiple feeds with optional rate limiting."""
        results = []
        for i, url in enumerate(urls):
            if i > 0:
                await asyncio.sleep(delay)
            result = await self.fetch_feed(url)
            results.append(result)
        return results

    async def search_for_feeds(self, topic: str) -> list[str]:
        """Suggest common RSS feed sources for a given topic."""
        # Common RSS sources by category
        suggestions = []

        topic_lower = topic.lower()

        # Generic feeds
        suggestions.extend([
            f"https://news.google.com/rss/search?q={topic.replace(' ', '+')}",
            f"https://www.reddit.com/search.rss?q={topic.replace(' ', '+')}&sort=new",
        ])

        return suggestions

    def filter_recent(
        self,
        entries: list[dict],
        days: int = 7,
    ) -> list[dict]:
        """Filter entries published within the last N days."""
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = []

        for entry in entries:
            pub = entry.get("published")
            if not pub:
                recent.append(entry)  # Include entries without dates
                continue
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if pub_dt >= cutoff:
                    recent.append(entry)
            except Exception:
                recent.append(entry)

        return recent
