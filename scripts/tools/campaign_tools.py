"""Campaign analytics and strategy tools.

All tools that need AI generation return structured data + a prompt template.
The calling agent uses its own model to generate the final analysis.
"""

from __future__ import annotations

import json
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from scripts.shared.config import load_config
from scripts.shared.patreon_client import PatreonClient


def register(mcp: FastMCP) -> None:
    """Register campaign tools with the MCP server."""

    @mcp.tool()
    async def patreon_get_identity() -> str:
        """
        Get the authenticated creator's profile and linked campaign summary.
        Use this to confirm credentials and get the creator's user ID.
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            data = await client.get_identity()
        user = data.get("data", {})
        attrs = user.get("attributes", {})
        return json.dumps(
            {
                "user_id": user.get("id"),
                "name": attrs.get("full_name"),
                "email": attrs.get("email"),
                "url": attrs.get("url"),
                "vanity": attrs.get("vanity"),
                "about": attrs.get("about", "")[:500],
            },
            indent=2,
        )

    @mcp.tool()
    async def patreon_check_connection() -> str:
        """
        Test the Patreon API connection and verify that credentials are valid.
        Returns connection status, user name, and available campaigns.
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            identity = await client.get_identity(include_campaigns=True)
            campaigns = await client.get_campaigns(include_tiers=False)

        user = identity.get("data", {})
        attrs = user.get("attributes", {})
        campaign_list = [
            {
                "id": c.get("id"),
                "name": c.get("attributes", {}).get("creation_name"),
            }
            for c in campaigns.get("data", [])
        ]
        return json.dumps(
            {
                "status": "connected",
                "user_id": user.get("id"),
                "name": attrs.get("full_name"),
                "campaigns": campaign_list,
                "campaign_count": len(campaign_list),
            },
            indent=2,
        )

    @mcp.tool()
    async def campaign_get_overview() -> str:
        """
        Get a comprehensive overview of all your Patreon campaigns.
        Returns MRR, patron count, tier summary, goals, campaign URLs.
        Use this as the starting point for any campaign analysis.
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaigns = await client.get_campaigns(include_tiers=True)

        results = []
        for c in campaigns.get("data", []):
            attrs = c.get("attributes", {})
            pledge_sum = attrs.get("pledge_sum", 0)
            results.append(
                {
                    "campaign_id": c.get("id"),
                    "creation_name": attrs.get("creation_name"),
                    "patron_count": attrs.get("patron_count", 0),
                    "mrr_cents": pledge_sum,
                    "mrr": f"${pledge_sum / 100:.2f}",
                    "url": attrs.get("url"),
                    "one_liner": attrs.get("one_liner", ""),
                    "is_monthly": attrs.get("is_monthly", True),
                    "created_at": attrs.get("created_at"),
                    "published_at": attrs.get("published_at"),
                }
            )
        return json.dumps(
            {"campaigns": results, "total_campaigns": len(results)},
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def campaign_analyze_tiers(campaign_id: str) -> str:
        """
        Analyze the tier structure of a campaign: prices, member counts,
        estimated revenue per tier, descriptions. Returns raw data plus
        a prompt template for your agent to generate optimization advice.

        Args:
            campaign_id: Patreon campaign ID (from campaign_get_overview)
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        included = campaign.get("included", [])
        tiers = sorted(
            [i for i in included if i.get("type") == "tier"],
            key=lambda t: t.get("attributes", {}).get("amount_cents", 0),
        )
        campaign_attrs = campaign.get("data", {}).get("attributes", {})

        tier_data = []
        total_revenue = 0
        for t in tiers:
            a = t.get("attributes", {})
            patrons = a.get("patron_count", 0)
            cents = a.get("amount_cents", 0)
            revenue = patrons * cents
            total_revenue += revenue
            tier_data.append(
                {
                    "id": t.get("id"),
                    "title": a.get("title"),
                    "price": f"${cents / 100:.2f}",
                    "price_cents": cents,
                    "patron_count": patrons,
                    "monthly_revenue": f"${revenue / 100:.2f}",
                    "description": (a.get("description") or "")[:300],
                    "is_published": bool(a.get("published_at")),
                    "post_count": a.get("post_count", 0),
                }
            )

        for t in tier_data:
            t["revenue_share"] = (
                f"{(t['price_cents'] * t['patron_count']) / max(total_revenue, 1) * 100:.1f}%"
            )

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "creation_name": campaign_attrs.get("creation_name"),
                "tiers": tier_data,
                "tier_count": len(tier_data),
                "total_estimated_mrr": f"${total_revenue / 100:.2f}",
                "analysis_prompt": (
                    f"Analyze these Patreon tiers for '{campaign_attrs.get('creation_name')}':\n"
                    f"{json.dumps(tier_data, indent=2)}\n\n"
                    "Provide: 1) Which tiers perform best 2) Price gap analysis "
                    "3) Tier description quality 4) Recommendations for new/adjusted tiers"
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def campaign_track_goals(campaign_id: str) -> str:
        """
        Get all campaign goals with progress percentages and completion status.
        Useful for tracking milestones and communicating progress to patrons.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        included = campaign.get("included", [])
        goals = [i for i in included if i.get("type") == "goal"]
        campaign_attrs = campaign.get("data", {}).get("attributes", {})
        current_pledge = campaign_attrs.get("pledge_sum", 0)

        goal_data = []
        for g in goals:
            a = g.get("attributes", {})
            goal_cents = a.get("amount_cents", 0)
            pct = a.get("completed_percentage", 0)
            goal_data.append(
                {
                    "id": g.get("id"),
                    "title": a.get("title"),
                    "description": (a.get("description") or "")[:300],
                    "target": f"${goal_cents / 100:.2f}",
                    "target_cents": goal_cents,
                    "completed_percentage": pct,
                    "is_completed": pct >= 100,
                    "reached_at": a.get("reached_at"),
                }
            )

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "current_mrr": f"${current_pledge / 100:.2f}",
                "current_mrr_cents": current_pledge,
                "goals": goal_data,
                "total_goals": len(goal_data),
                "completed_goals": sum(1 for g in goal_data if g["is_completed"]),
                "next_goal": next(
                    (g for g in goal_data if not g["is_completed"]), None
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def campaign_revenue_breakdown(campaign_id: str) -> str:
        """
        Detailed revenue breakdown: MRR by tier, average revenue per patron,
        revenue concentration risk. Includes a prompt for AI revenue forecasting.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        included = campaign.get("included", [])
        tiers = [i for i in included if i.get("type") == "tier"]
        ca = campaign.get("data", {}).get("attributes", {})

        breakdown = []
        total_cents = 0
        for t in tiers:
            a = t.get("attributes", {})
            patrons = a.get("patron_count", 0)
            cents = a.get("amount_cents", 0)
            revenue = patrons * cents
            total_cents += revenue
            breakdown.append(
                {
                    "tier": a.get("title"),
                    "price": f"${cents / 100:.2f}",
                    "patrons": patrons,
                    "monthly_revenue": f"${revenue / 100:.2f}",
                    "monthly_revenue_cents": revenue,
                }
            )

        breakdown.sort(key=lambda x: x["monthly_revenue_cents"], reverse=True)
        for b in breakdown:
            b["revenue_share"] = (
                f"{b['monthly_revenue_cents'] / max(total_cents, 1) * 100:.1f}%"
            )

        patron_count = ca.get("patron_count", 0)
        arpp = total_cents / max(patron_count, 1) / 100  # avg revenue per patron

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "total_mrr": f"${total_cents / 100:.2f}",
                "total_mrr_cents": total_cents,
                "patron_count": patron_count,
                "avg_revenue_per_patron": f"${arpp:.2f}",
                "tier_breakdown": breakdown,
                "forecast_prompt": (
                    f"Given this Patreon revenue data, provide a 3 and 6-month revenue forecast "
                    f"with assumptions. Current MRR: ${total_cents / 100:.2f}, "
                    f"Patrons: {patron_count}, ARPP: ${arpp:.2f}. "
                    f"Tier data: {json.dumps(breakdown)}"
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def campaign_suggest_tier_optimization(
        campaign_id: str, niche: str = ""
    ) -> str:
        """
        Return current tier data + a prompt for AI-powered tier optimization advice.
        Pass the output to your agent model to get specific pricing recommendations.

        Args:
            campaign_id: Patreon campaign ID
            niche: Creator category, e.g. 'fantasy author', 'indie musician' (optional)
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        included = campaign.get("included", [])
        tiers = sorted(
            [i for i in included if i.get("type") == "tier"],
            key=lambda t: t.get("attributes", {}).get("amount_cents", 0),
        )
        ca = campaign.get("data", {}).get("attributes", {})

        tier_data = [
            {
                "title": t.get("attributes", {}).get("title"),
                "price_usd": t.get("attributes", {}).get("amount_cents", 0) / 100,
                "patrons": t.get("attributes", {}).get("patron_count", 0),
                "description": (t.get("attributes", {}).get("description") or "")[:300],
            }
            for t in tiers
        ]

        prices = [t["price_usd"] for t in tier_data]

        return json.dumps(
            {
                "current_tiers": tier_data,
                "creation_name": ca.get("creation_name"),
                "niche": niche,
                "price_range": {"min": min(prices) if prices else 0, "max": max(prices) if prices else 0},
                "optimization_prompt": (
                    f"You are a Patreon monetization expert. Analyze these tiers for "
                    f"'{ca.get('creation_name')}' ({niche or 'unspecified niche'}):\n\n"
                    f"{json.dumps(tier_data, indent=2)}\n\nProvide: "
                    "1) Price point gaps 2) Description improvements "
                    "3) Recommended new tiers 4) Which tiers to remove/merge "
                    "5) Upsell funnel strategy from lowest to highest tier"
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def campaign_generate_growth_strategy(
        campaign_id: str, niche: str = "", timeframe_days: int = 90
    ) -> str:
        """
        Compile full campaign data into a prompt for growth strategy generation.
        Pass the 'strategy_prompt' field to your agent model.

        Args:
            campaign_id: Patreon campaign ID
            niche: Creator niche/category description
            timeframe_days: Strategy timeframe in days (default 90)
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        included = campaign.get("included", [])
        tiers = [i for i in included if i.get("type") == "tier"]
        goals = [i for i in included if i.get("type") == "goal"]
        ca = campaign.get("data", {}).get("attributes", {})

        tier_summary = [
            {
                "title": t.get("attributes", {}).get("title"),
                "price": f"${t.get('attributes', {}).get('amount_cents', 0) / 100:.2f}",
                "patrons": t.get("attributes", {}).get("patron_count", 0),
            }
            for t in tiers
        ]

        return json.dumps(
            {
                "campaign_data": {
                    "creation_name": ca.get("creation_name"),
                    "patron_count": ca.get("patron_count", 0),
                    "mrr": f"${ca.get('pledge_sum', 0) / 100:.2f}",
                    "summary": (ca.get("summary") or "")[:500],
                    "niche": niche,
                    "tiers": tier_summary,
                    "active_goals": len([g for g in goals if g.get("attributes", {}).get("completed_percentage", 0) < 100]),
                },
                "strategy_prompt": (
                    f"Create a {timeframe_days}-day Patreon growth strategy for:\n"
                    f"Creator: {ca.get('creation_name')}\n"
                    f"Niche: {niche or 'Not specified'}\n"
                    f"Current patrons: {ca.get('patron_count', 0)}\n"
                    f"Monthly revenue: ${ca.get('pledge_sum', 0) / 100:.2f}\n"
                    f"Tiers: {json.dumps(tier_summary)}\n\n"
                    f"Include: 1) Patron acquisition tactics for this niche "
                    "2) Content strategy for retention 3) Specific milestones at 30/60/90 days "
                    "4) Promotion channels to prioritize 5) Churn reduction strategies "
                    "6) Revenue diversification beyond Patreon"
                ),
            },
            indent=2,
            default=str,
        )
