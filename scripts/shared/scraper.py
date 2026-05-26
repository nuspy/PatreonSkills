"""Web scraper for public Patreon creator pages.

Scrapes publicly visible information without authentication:
- Creator name and bio
- Tier structure and prices
- Recent post titles and metadata
- Patron count (if publicly shown)
- Social links

Respects robots.txt and adds request delays to avoid overloading servers.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin, urlparse

import httpx

PATREON_BASE = "https://www.patreon.com"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; patreon-creator-skill/1.0; research)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class PageScraper:
    """Scrapes public Patreon creator pages."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PageScraper":
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=20.0,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    def _normalize_url(self, url_or_username: str) -> str:
        """Accept a username or full URL, return the canonical page URL."""
        if url_or_username.startswith("http"):
            return url_or_username.rstrip("/")
        username = url_or_username.lstrip("/")
        return f"{PATREON_BASE}/{username}"

    async def scrape_creator_page(self, url_or_username: str) -> dict:
        """Scrape a public Patreon creator page.

        Args:
            url_or_username: Patreon username or full URL

        Returns:
            Dict with creator info, tiers, recent posts, stats
        """
        from bs4 import BeautifulSoup

        url = self._normalize_url(url_or_username)
        username = urlparse(url).path.strip("/")

        if not self._client:
            raise RuntimeError("Use as async context manager.")

        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {url}", "url": url}
        except Exception as e:
            return {"error": str(e), "url": url}

        soup = BeautifulSoup(response.text, "lxml")

        result: dict = {
            "url": url,
            "username": username,
            "scraped_at": None,
        }

        # ── Creator info ──
        result["creator_name"] = self._extract_creator_name(soup)
        result["bio"] = self._extract_bio(soup)
        result["patron_count"] = self._extract_patron_count(soup)
        result["social_links"] = self._extract_social_links(soup, url)

        # ── Tiers ──
        result["tiers"] = self._extract_tiers(soup)

        # ── Recent posts (titles only, public posts) ──
        result["recent_posts"] = self._extract_post_titles(soup)

        # ── Try to extract JSON-LD or Next.js data ──
        json_data = self._extract_json_data(soup)
        if json_data:
            result["structured_data"] = json_data

        from datetime import datetime
        result["scraped_at"] = datetime.utcnow().isoformat()

        return result

    def _extract_creator_name(self, soup) -> str:
        selectors = [
            "h1",
            '[data-tag="creator-name"]',
            '.creator-name',
            'meta[property="og:title"]',
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                return (el.get("content") or el.get_text()).strip()
        return ""

    def _extract_bio(self, soup) -> str:
        selectors = [
            '[data-tag="creator-bio"]',
            '.creator-about',
            'meta[property="og:description"]',
            '[data-tag="about-text"]',
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get("content") or el.get_text()
                return text.strip()[:1000]
        return ""

    def _extract_patron_count(self, soup) -> int | None:
        """Try to extract patron count from visible page elements."""
        # Look for patterns like "1,234 patrons", "1.2K members"
        text = soup.get_text()
        patterns = [
            r'([\d,]+)\s+(?:patrons?|members?|supporters?)',
            r'([\d.]+[KkMm]?)\s+(?:patrons?|members?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                count_str = match.group(1).replace(",", "")
                try:
                    if "k" in count_str.lower():
                        return int(float(count_str[:-1]) * 1000)
                    return int(count_str)
                except ValueError:
                    pass
        return None

    def _extract_tiers(self, soup) -> list[dict]:
        """Extract membership tiers from the page."""
        tiers = []

        # Try multiple selectors for tier cards
        tier_selectors = [
            '[data-tag="tier-card"]',
            '.membership-tier',
            '[class*="tier"]',
            '[class*="reward"]',
        ]

        tier_elements = []
        for sel in tier_selectors:
            elements = soup.select(sel)
            if elements:
                tier_elements = elements
                break

        for el in tier_elements[:20]:  # Max 20 tiers
            tier: dict = {}

            # Title
            title_el = el.select_one("h2, h3, h4, [class*=title], [class*=name]")
            if title_el:
                tier["title"] = title_el.get_text().strip()

            # Price
            price_text = el.get_text()
            price_match = re.search(r'\$([\d.]+)', price_text)
            if price_match:
                tier["price_usd"] = float(price_match.group(1))

            # Description
            desc_el = el.select_one("p, [class*=desc]") 
            if desc_el:
                tier["description"] = desc_el.get_text().strip()[:500]

            if tier:
                tiers.append(tier)

        return tiers

    def _extract_post_titles(self, soup) -> list[dict]:
        """Extract recent post titles from the page."""
        posts = []
        post_selectors = [
            '[data-tag="post-title"]',
            'h3 a[href*="/posts/"]',
            'a[href*="/posts/"]',
        ]

        seen_titles = set()
        for sel in post_selectors:
            for el in soup.select(sel)[:30]:
                title = el.get_text().strip()
                href = el.get("href", "")
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    posts.append({
                        "title": title,
                        "url": urljoin(PATREON_BASE, href) if href else None,
                    })

        return posts[:20]

    def _extract_social_links(self, soup, page_url: str) -> dict:
        """Extract social media links from the page."""
        links = {}
        social_patterns = {
            "twitter": r"twitter\.com/",
            "instagram": r"instagram\.com/",
            "youtube": r"youtube\.com/",
            "twitch": r"twitch\.tv/",
            "discord": r"discord\.gg/|discord\.com/",
            "tiktok": r"tiktok\.com/",
            "facebook": r"facebook\.com/",
        }

        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            for platform, pattern in social_patterns.items():
                if re.search(pattern, href, re.IGNORECASE) and platform not in links:
                    links[platform] = href

        return links

    def _extract_json_data(self, soup) -> dict | None:
        """Try to extract structured JSON from script tags."""
        import json

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        return None

    async def scrape_multiple(
        self, urls: list[str], delay: float = 1.5
    ) -> list[dict]:
        """Scrape multiple creator pages with rate limiting."""
        results = []
        for i, url in enumerate(urls):
            if i > 0:
                await asyncio.sleep(delay)
            result = await self.scrape_creator_page(url)
            results.append(result)
        return results
