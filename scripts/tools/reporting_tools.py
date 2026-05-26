"""Reporting and monitoring tools.

Monthly summaries, member exports, growth analysis, revenue forecasting,
competitive benchmarking, and RSS trend monitoring.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from mcp.server.fastmcp import FastMCP

from scripts.shared.config import load_config
from scripts.shared.patreon_client import PatreonClient


def _parse_dt(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def register(mcp: FastMCP) -> None:
    """Register reporting and monitoring tools."""

    @mcp.tool()
    async def report_monthly_summary(campaign_id: str) -> str:
        """
        Generate a comprehensive monthly performance summary.
        Includes: revenue, patron metrics, new vs churned, post activity.
        Returns data + a prompt for your agent to write the narrative report.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)

        stats = {
            "active": 0, "new_this_month": 0, "churned_this_month": 0,
            "declined": 0, "pledge_sum": 0,
        }

        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)
            ca = campaign.get("data", {}).get("attributes", {})

            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                status = a.get("patron_status", "")

                if status == "active_patron":
                    stats["active"] += 1
                    stats["pledge_sum"] += a.get("currently_entitled_amount_cents", 0)

                    join_dt = _parse_dt(a.get("pledge_relationship_start"))
                    if join_dt:
                        jdt = join_dt.replace(tzinfo=timezone.utc) if join_dt.tzinfo is None else join_dt
                        if jdt >= month_start:
                            stats["new_this_month"] += 1

                elif status == "declined_patron":
                    stats["declined"] += 1

                elif status == "former_patron":
                    last = _parse_dt(a.get("last_charge_date"))
                    if last:
                        ldt = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
                        if ldt >= month_start:
                            stats["churned_this_month"] += 1

            # Posts this month
            posts_this_month = 0
            async for p in client.get_all_posts(campaign_id):
                pub = _parse_dt(p.get("attributes", {}).get("published_at"))
                if pub:
                    pdt = pub.replace(tzinfo=timezone.utc) if pub.tzinfo is None else pub
                    if pdt >= month_start:
                        posts_this_month += 1

        net_change = stats["new_this_month"] - stats["churned_this_month"]
        mrr = stats["pledge_sum"] / 100

        summary = {
            "campaign_id": campaign_id,
            "creation_name": ca.get("creation_name"),
            "report_month": now.strftime("%B %Y"),
            "total_active_patrons": stats["active"],
            "new_patrons": stats["new_this_month"],
            "churned_patrons": stats["churned_this_month"],
            "net_patron_change": net_change,
            "declined_patrons": stats["declined"],
            "total_mrr": f"${mrr:.2f}",
            "posts_published": posts_this_month,
            "patron_growth_trend": "positive" if net_change > 0 else "negative" if net_change < 0 else "flat",
        }

        return json.dumps(
            {
                **summary,
                "report_prompt": (
                    f"Write a monthly Patreon performance report for '{ca.get('creation_name')}' "
                    f"for {now.strftime('%B %Y')}:\n\n"
                    f"{json.dumps(summary, indent=2)}\n\n"
                    "Write a professional creator update covering:\n"
                    "1) Headline metrics (patrons, revenue)\n"
                    "2) Growth analysis (what drove new patrons, why people churned)\n"
                    "3) Content performance (posts published)\n"
                    "4) Action items for next month\n"
                    "5) A short thank-you message to patrons"
                ),
            },
            indent=2,
        )

    @mcp.tool()
    async def report_export_members(
        campaign_id: str,
        format: str = "json",
        status_filter: str = "active_patron",
    ) -> str:
        """
        Export the full member list as JSON or CSV.

        Args:
            campaign_id: Patreon campaign ID
            format: 'json' or 'csv'
            status_filter: 'active_patron', 'former_patron', 'declined_patron', or '' for all
        """
        config = load_config()
        members = []

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                if status_filter and a.get("patron_status") != status_filter:
                    continue
                members.append(
                    {
                        "id": m.get("id"),
                        "name": a.get("full_name", "Anonymous"),
                        "patron_status": a.get("patron_status"),
                        "pledge_usd": a.get("currently_entitled_amount_cents", 0) / 100,
                        "lifetime_usd": a.get("lifetime_support_cents", 0) / 100,
                        "joined": a.get("pledge_relationship_start", ""),
                        "last_charge_date": a.get("last_charge_date", ""),
                        "last_charge_status": a.get("last_charge_status", ""),
                    }
                )

        if format.lower() == "csv":
            if not members:
                return json.dumps({"format": "csv", "data": "", "count": 0})

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=members[0].keys())
            writer.writeheader()
            writer.writerows(members)
            csv_data = output.getvalue()

            return json.dumps(
                {
                    "format": "csv",
                    "member_count": len(members),
                    "status_filter": status_filter,
                    "csv_data": csv_data,
                    "note": "Save the 'csv_data' field content to a .csv file.",
                },
                indent=2,
            )

        return json.dumps(
            {
                "format": "json",
                "member_count": len(members),
                "status_filter": status_filter,
                "members": members,
            },
            indent=2,
        )

    @mcp.tool()
    async def report_growth_analysis(
        campaign_id: str, months_back: int = 6
    ) -> str:
        """
        Analyze patron growth trends over the past N months.
        Groups join/churn events by month to show growth trajectory.

        Args:
            campaign_id: Patreon campaign ID
            months_back: How many months to analyze (default 6)
        """
        config = load_config()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=months_back * 30)

        monthly_joins: dict = defaultdict(int)
        monthly_churn: dict = defaultdict(int)

        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)
            ca = campaign.get("data", {}).get("attributes", {})

            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                status = a.get("patron_status", "")

                join_dt = _parse_dt(a.get("pledge_relationship_start"))
                if join_dt:
                    jdt = join_dt.replace(tzinfo=timezone.utc) if join_dt.tzinfo is None else join_dt
                    if jdt >= cutoff:
                        month_key = jdt.strftime("%Y-%m")
                        monthly_joins[month_key] += 1

                if status == "former_patron":
                    last = _parse_dt(a.get("last_charge_date"))
                    if last:
                        ldt = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
                        if ldt >= cutoff:
                            month_key = ldt.strftime("%Y-%m")
                            monthly_churn[month_key] += 1

        # Build timeline
        all_months = sorted(set(list(monthly_joins.keys()) + list(monthly_churn.keys())))
        timeline = [
            {
                "month": m,
                "new_patrons": monthly_joins.get(m, 0),
                "churned": monthly_churn.get(m, 0),
                "net": monthly_joins.get(m, 0) - monthly_churn.get(m, 0),
            }
            for m in all_months
        ]

        total_new = sum(monthly_joins.values())
        total_churned = sum(monthly_churn.values())

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "creation_name": ca.get("creation_name"),
                "analysis_period_months": months_back,
                "total_new_patrons": total_new,
                "total_churned": total_churned,
                "net_growth": total_new - total_churned,
                "monthly_timeline": timeline,
                "current_patron_count": ca.get("patron_count", 0),
            },
            indent=2,
        )

    @mcp.tool()
    async def report_revenue_forecast(
        campaign_id: str, forecast_months: int = 3
    ) -> str:
        """
        Compile current revenue data into a forecast prompt.
        Returns data + a prompt for your agent to generate revenue projections.

        Args:
            campaign_id: Patreon campaign ID
            forecast_months: Months to forecast (default 3)
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        ca = campaign.get("data", {}).get("attributes", {})
        included = campaign.get("included", [])
        tiers = [i for i in included if i.get("type") == "tier"]

        tier_data = [
            {
                "tier": t.get("attributes", {}).get("title"),
                "price_usd": t.get("attributes", {}).get("amount_cents", 0) / 100,
                "patrons": t.get("attributes", {}).get("patron_count", 0),
                "mrr": t.get("attributes", {}).get("amount_cents", 0) * t.get("attributes", {}).get("patron_count", 0) / 100,
            }
            for t in tiers
        ]

        current_mrr = ca.get("pledge_sum", 0) / 100
        patron_count = ca.get("patron_count", 0)

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "current_mrr": f"${current_mrr:.2f}",
                "patron_count": patron_count,
                "tier_breakdown": tier_data,
                "forecast_prompt": (
                    f"Generate a {forecast_months}-month revenue forecast for this Patreon campaign:\n\n"
                    f"Current MRR: ${current_mrr:.2f}\n"
                    f"Current patrons: {patron_count}\n"
                    f"Tier breakdown: {json.dumps(tier_data)}\n\n"
                    f"Provide three scenarios:\n"
                    f"1. Conservative (5-10% monthly growth)\n"
                    f"2. Moderate (10-20% monthly growth)\n"
                    f"3. Optimistic (20-30% monthly growth)\n\n"
                    "For each scenario show month-by-month MRR and patron count projections. "
                    "Include key assumptions and risks."
                ),
            },
            indent=2,
        )

    @mcp.tool()
    async def report_competitive_benchmark(
        campaign_id: str, competitor_usernames: str
    ) -> str:
        """
        Generate a competitive benchmark report comparing your campaign
        against scraped competitor data. Returns data + analysis prompt.

        Args:
            campaign_id: Your Patreon campaign ID
            competitor_usernames: Comma-separated Patreon usernames to benchmark against
        """
        from scripts.shared.scraper import PageScraper

        config = load_config()

        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        ca = campaign.get("data", {}).get("attributes", {})
        included = campaign.get("included", [])
        tiers = [i for i in included if i.get("type") == "tier"]

        your_data = {
            "name": ca.get("creation_name"),
            "patron_count": ca.get("patron_count", 0),
            "mrr": f"${ca.get('pledge_sum', 0) / 100:.2f}",
            "tier_count": len(tiers),
            "tier_prices": sorted([
                t.get("attributes", {}).get("amount_cents", 0) / 100 for t in tiers
            ]),
        }

        urls = [u.strip() for u in competitor_usernames.split(",") if u.strip()][:5]
        competitor_data = []

        async with PageScraper() as scraper:
            for url in urls:
                page = await scraper.scrape_creator_page(url)
                tiers_scraped = page.get("tiers", [])
                competitor_data.append(
                    {
                        "name": page.get("creator_name") or page.get("username"),
                        "patron_count": page.get("patron_count"),
                        "tier_count": len(tiers_scraped),
                        "tier_prices": sorted([
                            t.get("price_usd", 0) for t in tiers_scraped if t.get("price_usd")
                        ]),
                        "recent_post_count": len(page.get("recent_posts", [])),
                    }
                )

        return json.dumps(
            {
                "your_campaign": your_data,
                "competitors": competitor_data,
                "benchmark_prompt": (
                    f"Create a competitive benchmark report for '{ca.get('creation_name')}':\n\n"
                    f"YOUR DATA:\n{json.dumps(your_data, indent=2)}\n\n"
                    f"COMPETITORS:\n{json.dumps(competitor_data, indent=2)}\n\n"
                    "Provide:\n"
                    "1) Where you rank vs competitors (patrons, pricing)\n"
                    "2) Your competitive strengths and weaknesses\n"
                    "3) Opportunities the competition isn't exploiting\n"
                    "4) Recommended actions to improve your competitive position\n"
                    "5) Success metrics to track quarterly"
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def monitor_rss_trends(
        feed_urls: str,
        topic: str = "",
        days_recent: int = 7,
    ) -> str:
        """
        Monitor RSS/Atom feeds for recent content trends in your niche.
        Useful for finding trending topics to create content about.

        Args:
            feed_urls: Comma-separated RSS feed URLs to monitor.
                       If empty, suggests feeds based on topic.
            topic: Creator niche/topic for feed suggestions (if no URLs provided)
            days_recent: Show only entries from last N days (default 7)
        """
        from scripts.shared.rss_monitor import RSSMonitor

        urls = [u.strip() for u in feed_urls.split(",") if u.strip()]

        async with RSSMonitor() as monitor:
            if not urls and topic:
                urls = await monitor.search_for_feeds(topic)

            if not urls:
                return json.dumps(
                    {
                        "error": "No feed URLs provided and no topic to auto-suggest feeds.",
                        "hint": "Provide RSS feed URLs or set the 'topic' parameter.",
                    },
                    indent=2,
                )

            feeds = await monitor.fetch_multiple(urls[:10])

        # Filter recent entries
        all_entries = []
        for feed in feeds:
            recent = monitor.filter_recent(feed.get("entries", []), days=days_recent)
            for e in recent:
                e["feed_title"] = feed.get("feed_title", "")
                e["feed_url"] = feed.get("url", "")
            all_entries.extend(recent)

        # Sort by published date
        all_entries.sort(key=lambda x: x.get("published", ""), reverse=True)

        return json.dumps(
            {
                "feeds_monitored": len(feeds),
                "total_recent_entries": len(all_entries),
                "period_days": days_recent,
                "entries": all_entries[:30],
                "trend_prompt": (
                    f"Analyze these {len(all_entries)} recent articles/posts from niche feeds. "
                    f"Identify the top 5 trending topics that a Patreon creator "
                    f"({topic or 'in this space'}) could create content about:\n\n"
                    + "\n".join(
                        f"- {e.get('title', '')} ({e.get('feed_title', '')})"
                        for e in all_entries[:20]
                        if e.get('title')
                    )
                ),
            },
            indent=2,
            default=str,
        )
