"""Competitor intelligence tools.

Analyze competitor Patreon pages, track trends, and generate strategic insights.
Uses web scraping (public pages only), Google/Bing search, and RSS feeds.
"""

from __future__ import annotations

import json
from collections import Counter

from mcp.server.fastmcp import FastMCP

from scripts.shared.config import load_config
from scripts.shared.patreon_client import PatreonClient


def register(mcp: FastMCP) -> None:
    """Register competitor intelligence tools."""

    @mcp.tool()
    async def competitor_analyze_patreon_page(patreon_url_or_username: str) -> str:
        """
        Scrape a public Patreon creator page to analyze:
        - Creator bio and positioning
        - Tier structure and pricing
        - Recent public post titles
        - Patron count (if visible)
        - Social media links

        Only accesses publicly visible information.

        Args:
            patreon_url_or_username: Patreon username or full URL
                                     (e.g., 'kurzgesagt' or 'https://www.patreon.com/kurzgesagt')
        """
        from scripts.shared.scraper import PageScraper

        async with PageScraper() as scraper:
            data = await scraper.scrape_creator_page(patreon_url_or_username)

        return json.dumps(data, indent=2, default=str)

    @mcp.tool()
    async def competitor_analyze_multiple_pages(usernames: str) -> str:
        """
        Scrape multiple competitor Patreon pages at once.
        Useful for benchmarking across several creators in your niche.

        Args:
            usernames: Comma-separated Patreon usernames or URLs
                       (e.g., 'creator1,creator2,creator3')
        """
        from scripts.shared.scraper import PageScraper

        urls = [u.strip() for u in usernames.split(",") if u.strip()]
        if not urls:
            return json.dumps({"error": "No usernames provided"}, indent=2)
        if len(urls) > 10:
            return json.dumps({"error": "Max 10 pages at once"}, indent=2)

        async with PageScraper() as scraper:
            results = await scraper.scrape_multiple(urls)

        return json.dumps(
            {"analyzed": len(results), "pages": results}, indent=2, default=str
        )

    @mcp.tool()
    async def competitor_compare_tiers(
        campaign_id: str, competitor_usernames: str
    ) -> str:
        """
        Compare your tier structure against competitor pages.
        Returns a side-by-side comparison with a prompt for strategic recommendations.

        Args:
            campaign_id: Your Patreon campaign ID
            competitor_usernames: Comma-separated Patreon usernames to compare against
        """
        from scripts.shared.scraper import PageScraper

        config = load_config()

        # Fetch your tiers
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        included = campaign.get("included", [])
        tiers = [i for i in included if i.get("type") == "tier"]
        ca = campaign.get("data", {}).get("attributes", {})

        your_tiers = sorted(
            [
                {
                    "title": t.get("attributes", {}).get("title"),
                    "price_usd": t.get("attributes", {}).get("amount_cents", 0) / 100,
                    "patrons": t.get("attributes", {}).get("patron_count", 0),
                    "description": (t.get("attributes", {}).get("description") or "")[:200],
                }
                for t in tiers
            ],
            key=lambda x: x["price_usd"],
        )

        # Fetch competitor tiers
        urls = [u.strip() for u in competitor_usernames.split(",") if u.strip()][:5]
        competitor_data = []

        async with PageScraper() as scraper:
            for url in urls:
                page = await scraper.scrape_creator_page(url)
                competitor_data.append(
                    {
                        "username": page.get("username"),
                        "name": page.get("creator_name"),
                        "patron_count": page.get("patron_count"),
                        "tiers": page.get("tiers", []),
                    }
                )

        return json.dumps(
            {
                "your_campaign": {
                    "name": ca.get("creation_name"),
                    "tiers": your_tiers,
                    "patron_count": ca.get("patron_count", 0),
                },
                "competitors": competitor_data,
                "comparison_prompt": (
                    f"Compare these Patreon tier structures:\n\n"
                    f"YOUR TIERS ({ca.get('creation_name')}):\n"
                    f"{json.dumps(your_tiers, indent=2)}\n\n"
                    f"COMPETITORS:\n"
                    f"{json.dumps(competitor_data, indent=2)}\n\n"
                    "Provide: 1) Price positioning analysis 2) Missing tier opportunities "
                    "3) Benefits your competitors offer that you don't "
                    "4) How to differentiate your offering "
                    "5) Specific recommended changes based on the comparison"
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def competitor_track_posting_frequency(usernames: str) -> str:
        """
        Analyze posting cadence and content strategy of competitor creators.
        Useful for benchmarking your posting frequency and content mix.

        Args:
            usernames: Comma-separated Patreon usernames
        """
        from scripts.shared.scraper import PageScraper

        urls = [u.strip() for u in usernames.split(",") if u.strip()][:5]

        async with PageScraper() as scraper:
            pages = await scraper.scrape_multiple(urls)

        analysis = []
        for page in pages:
            posts = page.get("recent_posts", [])
            analysis.append(
                {
                    "username": page.get("username"),
                    "creator_name": page.get("creator_name"),
                    "recent_post_count": len(posts),
                    "recent_post_titles": [p["title"] for p in posts[:10]],
                    "patron_count": page.get("patron_count"),
                }
            )

        return json.dumps(
            {
                "analyzed_creators": analysis,
                "frequency_prompt": (
                    f"Analyze these Patreon creator posting patterns and recommend "
                    f"an optimal posting frequency:\n{json.dumps(analysis, indent=2)}\n\n"
                    "Provide: 1) Who posts most/least frequently "
                    "2) Content title patterns (what topics work) "
                    "3) Recommended posting frequency and types for a creator in this space"
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def competitor_search_web(
        query: str, num_results: int = 10, search_source: str = "auto"
    ) -> str:
        """
        Search the web for competitor intelligence, news, and trend data.
        Uses Google, Bing, or DuckDuckGo (auto-selects based on configured API keys).

        Args:
            query: Search query (e.g., 'top fantasy Patreon creators 2025')
            num_results: Number of results (max 20)
            search_source: 'google' | 'bing' | 'duckduckgo' | 'auto'
        """
        config = load_config()
        from scripts.shared.search_client import SearchClient

        client = SearchClient(config)
        results = await client.search(
            query, num_results=min(num_results, 20), source=search_source
        )

        return json.dumps(
            {
                "query": query,
                "source": search_source,
                "result_count": len(results),
                "results": results,
            },
            indent=2,
        )

    @mcp.tool()
    async def competitor_search_patreon_creators(
        keywords: str, num_per_keyword: int = 5
    ) -> str:
        """
        Search for Patreon creators in a specific niche/keywords.
        Returns creator page URLs you can analyze with competitor_analyze_patreon_page.

        Args:
            keywords: Comma-separated keywords/niches to search
            num_per_keyword: Results per keyword (max 10)
        """
        config = load_config()
        from scripts.shared.search_client import SearchClient

        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        if not kw_list:
            return json.dumps({"error": "No keywords provided"}, indent=2)

        client = SearchClient(config)
        results = await client.search_patreon_creators(
            kw_list, num_per_query=min(num_per_keyword, 10)
        )

        # Extract unique Patreon usernames
        patreon_pages = []
        seen_urls = set()
        for r in results:
            url = r.get("url", "")
            if "patreon.com/" in url and url not in seen_urls:
                seen_urls.add(url)
                patreon_pages.append(
                    {
                        "url": url,
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "keyword": r.get("keyword", ""),
                    }
                )

        return json.dumps(
            {
                "keywords": kw_list,
                "patreon_pages_found": len(patreon_pages),
                "pages": patreon_pages,
                "tip": "Use competitor_analyze_patreon_page with any URL above for detailed analysis.",
            },
            indent=2,
        )

    @mcp.tool()
    async def competitor_generate_strategy(
        campaign_id: str, competitor_data_json: str, niche: str = ""
    ) -> str:
        """
        Compile your campaign data + competitor analysis into a competitive strategy prompt.
        Pass 'strategy_prompt' to your agent model for a detailed strategic report.

        Args:
            campaign_id: Your Patreon campaign ID
            competitor_data_json: JSON string from competitor_analyze_patreon_page
            niche: Your creator niche for context
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        ca = campaign.get("data", {}).get("attributes", {})
        included = campaign.get("included", [])
        tiers = [i for i in included if i.get("type") == "tier"]

        try:
            competitor_data = json.loads(competitor_data_json)
        except (json.JSONDecodeError, TypeError):
            competitor_data = {"note": "Could not parse competitor data"}

        your_summary = {
            "name": ca.get("creation_name"),
            "patron_count": ca.get("patron_count", 0),
            "mrr": f"${ca.get('pledge_sum', 0) / 100:.2f}",
            "tier_count": len(tiers),
            "tier_prices": [
                f"${t.get('attributes', {}).get('amount_cents', 0) / 100:.2f}" for t in tiers
            ],
            "niche": niche,
        }

        return json.dumps(
            {
                "your_campaign": your_summary,
                "competitor_summary": competitor_data,
                "strategy_prompt": (
                    f"You are a Patreon growth strategist. Create a competitive strategy for "
                    f"'{ca.get('creation_name')}' ({niche or 'general creator'})\n\n"
                    f"YOUR DATA:\n{json.dumps(your_summary, indent=2)}\n\n"
                    f"COMPETITOR DATA:\n{json.dumps(competitor_data, indent=2)}\n\n"
                    "Provide:\n"
                    "1) Competitive advantages you currently have\n"
                    "2) Key gaps vs competitors (price, content, benefits)\n"
                    "3) 3 quick wins (actions within 2 weeks)\n"
                    "4) 3 medium-term strategies (1-3 months)\n"
                    "5) How to position your page uniquely vs competitors\n"
                    "6) Content topics competitors aren't covering (opportunity)"
                ),
            },
            indent=2,
            default=str,
        )
