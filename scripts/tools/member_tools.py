"""Supporter analytics tools.

Full analysis of patron base: demographics, churn risk, cohorts, segmentation,
geographic distribution, language analysis, LTV, top supporters.

All AI-insights tools return data + prompt for the calling agent's model.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

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


def _months_since(dt: datetime | None) -> float:
    if not dt:
        return 0.0
    now = datetime.now(timezone.utc)
    delta = now - dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else now - dt
    return delta.days / 30.44


def register(mcp: FastMCP) -> None:
    """Register member analytics tools."""

    @mcp.tool()
    async def members_fetch_all(
        campaign_id: str,
        status_filter: str = "active_patron",
        limit: int = 0,
    ) -> str:
        """
        Fetch all campaign members with their tier, pledge status, and join date.
        Returns paginated member list (handles cursor pagination automatically).

        Args:
            campaign_id: Patreon campaign ID
            status_filter: 'active_patron', 'declined_patron', 'former_patron', or '' for all
            limit: Max members to return (0 = all)
        """
        config = load_config()
        members = []
        async with PatreonClient(config["access_token"]) as client:
            async for member in client.get_all_members(campaign_id):
                a = member.get("attributes", {})
                if status_filter and a.get("patron_status") != status_filter:
                    continue
                members.append(
                    {
                        "id": member.get("id"),
                        "name": a.get("full_name", "Anonymous"),
                        "status": a.get("patron_status"),
                        "charge_status": a.get("charge_status"),
                        "pledge_cents": a.get("currently_entitled_amount_cents", 0),
                        "lifetime_cents": a.get("lifetime_support_cents", 0),
                        "joined": a.get("pledge_relationship_start"),
                        "last_charge": a.get("last_charge_date"),
                        "last_charge_status": a.get("last_charge_status"),
                        "next_charge": a.get("next_charge_date"),
                    }
                )
                if limit and len(members) >= limit:
                    break

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "status_filter": status_filter,
                "total": len(members),
                "members": members,
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def members_analyze_demographics(campaign_id: str) -> str:
        """
        Comprehensive demographic analysis of your patron base:
        tier distribution, tenure buckets, charge status breakdown,
        lifetime value stats, average pledge amount.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        members = []
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)
            async for m in client.get_all_members(campaign_id):
                members.append(m)

        active = [m for m in members if m.get("attributes", {}).get("patron_status") == "active_patron"]

        # Tier distribution
        tier_counter: Counter = Counter()
        pledge_sum = 0
        lifetime_values = []

        # Tenure buckets (months)
        tenure_buckets = {"<1m": 0, "1-3m": 0, "3-6m": 0, "6-12m": 0, ">12m": 0}

        for m in active:
            a = m.get("attributes", {})
            cents = a.get("currently_entitled_amount_cents", 0)
            pledge_sum += cents
            tier_counter[f"${cents / 100:.0f}"] += 1

            ltv = a.get("lifetime_support_cents", 0)
            if ltv:
                lifetime_values.append(ltv / 100)

            months = _months_since(_parse_dt(a.get("pledge_relationship_start")))
            if months < 1:
                tenure_buckets["<1m"] += 1
            elif months < 3:
                tenure_buckets["1-3m"] += 1
            elif months < 6:
                tenure_buckets["3-6m"] += 1
            elif months < 12:
                tenure_buckets["6-12m"] += 1
            else:
                tenure_buckets[">12m"] += 1

        n_active = max(len(active), 1)
        avg_pledge = pledge_sum / n_active / 100
        avg_ltv = sum(lifetime_values) / max(len(lifetime_values), 1)

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "total_members": len(members),
                "active_patrons": len(active),
                "former_patrons": sum(1 for m in members if m.get("attributes", {}).get("patron_status") == "former_patron"),
                "declined_patrons": sum(1 for m in members if m.get("attributes", {}).get("patron_status") == "declined_patron"),
                "pledge_distribution": dict(tier_counter.most_common()),
                "tenure_distribution": tenure_buckets,
                "financial": {
                    "total_mrr": f"${pledge_sum / 100:.2f}",
                    "avg_pledge": f"${avg_pledge:.2f}",
                    "avg_lifetime_value": f"${avg_ltv:.2f}",
                    "max_lifetime_value": f"${max(lifetime_values, default=0):.2f}",
                },
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def members_detect_churn_risk(campaign_id: str) -> str:
        """
        Identify patrons at risk of churning based on:
        - Declined last charge
        - No charge in 45+ days with active status
        - Very short tenure (<2 months)

        Returns ranked list of at-risk patrons with risk factors.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        at_risk = []
        now = datetime.now(timezone.utc)

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                status = a.get("patron_status", "")
                if status not in ("active_patron", "declined_patron"):
                    continue

                risk_factors = []
                risk_score = 0

                # Declined payment
                if a.get("charge_status") == "Declined":
                    risk_factors.append("payment_declined")
                    risk_score += 3

                # Last charge more than 45 days ago
                last_charge = _parse_dt(a.get("last_charge_date"))
                if last_charge:
                    days_since = (now - last_charge.replace(tzinfo=timezone.utc) if last_charge.tzinfo is None else now - last_charge).days
                    if days_since > 45:
                        risk_factors.append(f"no_charge_{days_since}d")
                        risk_score += 2

                # Short tenure (<2 months)
                join_dt = _parse_dt(a.get("pledge_relationship_start"))
                months = _months_since(join_dt)
                if months < 2:
                    risk_factors.append("new_patron_<2m")
                    risk_score += 1

                if risk_factors:
                    at_risk.append(
                        {
                            "id": m.get("id"),
                            "name": a.get("full_name", "Anonymous"),
                            "status": status,
                            "pledge": f"${a.get('currently_entitled_amount_cents', 0) / 100:.2f}",
                            "tenure_months": round(months, 1),
                            "risk_score": risk_score,
                            "risk_factors": risk_factors,
                        }
                    )

        at_risk.sort(key=lambda x: x["risk_score"], reverse=True)

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "at_risk_count": len(at_risk),
                "at_risk_patrons": at_risk[:50],
                "retention_prompt": (
                    f"{len(at_risk)} patrons are at risk. Suggest 5 specific retention "
                    "strategies for a Patreon creator to re-engage them, based on "
                    f"risk factors: {json.dumps(list({f for p in at_risk for f in p['risk_factors']}))}"
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def members_cohort_analysis(campaign_id: str) -> str:
        """
        Cohort retention analysis: groups patrons by the month they joined
        and shows how many from each cohort are still active.
        Helps identify when churn is highest.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        cohorts: dict = defaultdict(lambda: {"joined": 0, "still_active": 0, "total_ltv": 0})

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                join_dt = _parse_dt(a.get("pledge_relationship_start"))
                if not join_dt:
                    continue
                cohort_key = join_dt.strftime("%Y-%m")
                cohorts[cohort_key]["joined"] += 1
                cohorts[cohort_key]["total_ltv"] += a.get("lifetime_support_cents", 0) / 100
                if a.get("patron_status") == "active_patron":
                    cohorts[cohort_key]["still_active"] += 1

        result = []
        for month in sorted(cohorts.keys()):
            c = cohorts[month]
            retention = c["still_active"] / max(c["joined"], 1)
            result.append(
                {
                    "cohort": month,
                    "joined": c["joined"],
                    "still_active": c["still_active"],
                    "retention_rate": f"{retention * 100:.1f}%",
                    "avg_ltv": f"${c['total_ltv'] / max(c['joined'], 1):.2f}",
                }
            )

        overall_retention = sum(c["still_active"] for c in cohorts.values()) / max(
            sum(c["joined"] for c in cohorts.values()), 1
        )

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "overall_retention_rate": f"{overall_retention * 100:.1f}%",
                "cohorts": result,
                "cohort_count": len(result),
            },
            indent=2,
        )

    @mcp.tool()
    async def members_segment(
        campaign_id: str,
        segment_by: str = "tier",
    ) -> str:
        """
        Segment patron base by different criteria.

        Args:
            campaign_id: Patreon campaign ID
            segment_by: 'tier' | 'tenure' | 'status' | 'charge_status'
        """
        config = load_config()
        segments: dict = defaultdict(list)

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})

                if segment_by == "tier":
                    key = f"${a.get('currently_entitled_amount_cents', 0) / 100:.0f}"
                elif segment_by == "tenure":
                    months = _months_since(_parse_dt(a.get("pledge_relationship_start")))
                    if months < 3:
                        key = "new (<3m)"
                    elif months < 12:
                        key = "regular (3-12m)"
                    else:
                        key = "veteran (>12m)"
                elif segment_by == "status":
                    key = a.get("patron_status", "unknown")
                elif segment_by == "charge_status":
                    key = a.get("charge_status", "unknown")
                else:
                    key = "all"

                segments[key].append({
                    "id": m.get("id"),
                    "name": a.get("full_name", "Anonymous"),
                    "pledge": f"${a.get('currently_entitled_amount_cents', 0) / 100:.2f}",
                })

        result = {
            seg: {"count": len(members), "members": members[:10], "total_shown": min(len(members), 10)}
            for seg, members in sorted(segments.items())
        }

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "segment_by": segment_by,
                "segments": result,
                "total_segments": len(result),
            },
            indent=2,
        )

    @mcp.tool()
    async def members_get_top_supporters(
        campaign_id: str,
        top_n: int = 20,
        rank_by: str = "lifetime_value",
    ) -> str:
        """
        Get top patrons ranked by lifetime value or current pledge.
        Useful for identifying VIP supporters and planning appreciation content.

        Args:
            campaign_id: Patreon campaign ID
            top_n: Number of top supporters to return
            rank_by: 'lifetime_value' | 'current_pledge' | 'tenure'
        """
        config = load_config()
        members = []

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                if a.get("patron_status") != "active_patron":
                    continue
                join_dt = _parse_dt(a.get("pledge_relationship_start"))
                members.append(
                    {
                        "id": m.get("id"),
                        "name": a.get("full_name", "Anonymous"),
                        "current_pledge": a.get("currently_entitled_amount_cents", 0) / 100,
                        "lifetime_value": a.get("lifetime_support_cents", 0) / 100,
                        "tenure_months": round(_months_since(join_dt), 1),
                        "joined": a.get("pledge_relationship_start"),
                    }
                )

        key_map = {
            "lifetime_value": lambda x: x["lifetime_value"],
            "current_pledge": lambda x: x["current_pledge"],
            "tenure": lambda x: x["tenure_months"],
        }
        sort_key = key_map.get(rank_by, key_map["lifetime_value"])
        members.sort(key=sort_key, reverse=True)

        for i, m in enumerate(members[:top_n]):
            m["rank"] = i + 1

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "rank_by": rank_by,
                "top_supporters": members[:top_n],
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def members_language_analysis(campaign_id: str) -> str:
        """
        Estimate language distribution of patron base by analyzing name patterns.
        Note: This is a heuristic estimate based on name origin, not definitive.
        Useful for deciding whether to create multilingual content.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        names = []

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                name = m.get("attributes", {}).get("full_name", "")
                if name:
                    names.append(name)

        # Character script detection
        script_counter: Counter = Counter()
        for name in names:
            has_cjk = any("一" <= c <= "鿿" or "぀" <= c <= "ヿ" for c in name)
            has_arabic = any("؀" <= c <= "ۿ" for c in name)
            has_cyrillic = any("Ѐ" <= c <= "ӿ" for c in name)
            has_latin = any("a" <= c.lower() <= "z" for c in name)

            if has_cjk:
                script_counter["CJK (Chinese/Japanese/Korean)"] += 1
            elif has_arabic:
                script_counter["Arabic/Persian"] += 1
            elif has_cyrillic:
                script_counter["Cyrillic (Russian/Eastern European)"] += 1
            elif has_latin:
                script_counter["Latin (English/European)"] += 1
            else:
                script_counter["Other/Unknown"] += 1

        total = max(len(names), 1)
        distribution = {
            script: {"count": count, "percentage": f"{count / total * 100:.1f}%"}
            for script, count in script_counter.most_common()
        }

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "analyzed_names": len(names),
                "script_distribution": distribution,
                "note": "Heuristic estimate based on name character scripts. Not definitive.",
                "multilingual_prompt": (
                    f"Based on this patron name script analysis: {json.dumps(distribution)}, "
                    "recommend whether this Patreon creator should create multilingual content, "
                    "and which languages to prioritize."
                ),
            },
            indent=2,
        )

    @mcp.tool()
    async def members_geographic_analysis(campaign_id: str) -> str:
        """
        Estimate geographic distribution by analyzing email domains and name patterns.
        Note: Geographic data is not directly available via the Patreon API.
        This is a best-effort heuristic analysis.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        domain_counter: Counter = Counter()
        tld_counter: Counter = Counter()
        total = 0

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                email = a.get("email", "")
                if email and "@" in email:
                    domain = email.split("@")[-1].lower()
                    tld = domain.split(".")[-1]
                    domain_counter[domain] += 1
                    tld_counter[tld] += 1
                    total += 1

        # Map TLDs to regions (rough heuristic)
        tld_to_region = {
            "com": "US/Global", "net": "US/Global", "org": "US/Global",
            "uk": "United Kingdom", "co": "Colombia/Global",
            "de": "Germany", "fr": "France", "it": "Italy",
            "es": "Spain", "nl": "Netherlands", "pl": "Poland",
            "ru": "Russia", "ua": "Ukraine", "cz": "Czech Republic",
            "br": "Brazil", "mx": "Mexico", "ar": "Argentina",
            "jp": "Japan", "kr": "South Korea", "cn": "China",
            "au": "Australia", "ca": "Canada", "in": "India",
        }

        region_counter: Counter = Counter()
        for tld, count in tld_counter.items():
            region = tld_to_region.get(tld, f"Other (.{tld})")
            region_counter[region] += count

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "analyzed_emails": total,
                "note": "Heuristic estimate based on email TLDs. Requires email scope.",
                "region_distribution": {
                    region: {"count": c, "pct": f"{c / max(total, 1) * 100:.1f}%"}
                    for region, c in region_counter.most_common(10)
                },
                "top_email_domains": dict(domain_counter.most_common(10)),
            },
            indent=2,
        )

    @mcp.tool()
    async def members_recent_activity(
        campaign_id: str, days: int = 30
    ) -> str:
        """
        Show patron activity in the last N days:
        new joins, upgrades (inferred), declines, former patrons.

        Args:
            campaign_id: Patreon campaign ID
            days: Lookback window in days (default 30)
        """
        config = load_config()
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta
        cutoff -= timedelta(days=days)

        new_joins = []
        declined = []
        former = []

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                status = a.get("patron_status", "")
                join_dt = _parse_dt(a.get("pledge_relationship_start"))
                last_charge_dt = _parse_dt(a.get("last_charge_date"))

                entry = {
                    "id": m.get("id"),
                    "name": a.get("full_name", "Anonymous"),
                    "pledge": f"${a.get('currently_entitled_amount_cents', 0) / 100:.2f}",
                }

                if join_dt:
                    jdt = join_dt.replace(tzinfo=timezone.utc) if join_dt.tzinfo is None else join_dt
                    if jdt >= cutoff:
                        new_joins.append({**entry, "joined": a.get("pledge_relationship_start")})

                if status == "declined_patron":
                    if last_charge_dt:
                        ldt = last_charge_dt.replace(tzinfo=timezone.utc) if last_charge_dt.tzinfo is None else last_charge_dt
                        if ldt >= cutoff:
                            declined.append(entry)

                if status == "former_patron" and last_charge_dt:
                    ldt = last_charge_dt.replace(tzinfo=timezone.utc) if last_charge_dt.tzinfo is None else last_charge_dt
                    if ldt >= cutoff:
                        former.append(entry)

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "period_days": days,
                "new_joins": {"count": len(new_joins), "patrons": new_joins},
                "payment_declined": {"count": len(declined), "patrons": declined},
                "churned": {"count": len(former), "patrons": former},
                "net_change": len(new_joins) - len(former),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def members_ai_insights(campaign_id: str) -> str:
        """
        Compile full patron analytics into a structured prompt for your AI agent.
        The 'insights_prompt' field contains a complete analysis request —
        pass it to your model to get narrative insights about your patron base.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        stats = {
            "active": 0, "declined": 0, "former": 0,
            "pledge_sum": 0, "ltv_sum": 0, "ltv_count": 0,
            "tenure_sum": 0,
        }
        tier_dist: Counter = Counter()
        tenure_buckets = {"<1m": 0, "1-3m": 0, "3-6m": 0, "6-12m": 0, ">12m": 0}

        async with PatreonClient(config["access_token"]) as client:
            async for m in client.get_all_members(campaign_id):
                a = m.get("attributes", {})
                status = a.get("patron_status", "")

                if status == "active_patron":
                    stats["active"] += 1
                    cents = a.get("currently_entitled_amount_cents", 0)
                    stats["pledge_sum"] += cents
                    tier_dist[f"${cents / 100:.0f}"] += 1

                    ltv = a.get("lifetime_support_cents", 0)
                    if ltv:
                        stats["ltv_sum"] += ltv
                        stats["ltv_count"] += 1

                    months = _months_since(_parse_dt(a.get("pledge_relationship_start")))
                    stats["tenure_sum"] += months

                    if months < 1:
                        tenure_buckets["<1m"] += 1
                    elif months < 3:
                        tenure_buckets["1-3m"] += 1
                    elif months < 6:
                        tenure_buckets["3-6m"] += 1
                    elif months < 12:
                        tenure_buckets["6-12m"] += 1
                    else:
                        tenure_buckets[">12m"] += 1

                elif status == "declined_patron":
                    stats["declined"] += 1
                elif status == "former_patron":
                    stats["former"] += 1

        n = max(stats["active"], 1)
        summary = {
            "active_patrons": stats["active"],
            "declined_patrons": stats["declined"],
            "former_patrons": stats["former"],
            "total_mrr": f"${stats['pledge_sum'] / 100:.2f}",
            "avg_pledge": f"${stats['pledge_sum'] / n / 100:.2f}",
            "avg_ltv": f"${stats['ltv_sum'] / max(stats['ltv_count'], 1) / 100:.2f}",
            "avg_tenure_months": round(stats["tenure_sum"] / n, 1),
            "tier_distribution": dict(tier_dist.most_common()),
            "tenure_distribution": tenure_buckets,
        }

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "summary": summary,
                "insights_prompt": (
                    f"Analyze this Patreon patron base and provide 5-7 key insights:\n"
                    f"{json.dumps(summary, indent=2)}\n\n"
                    "Focus on: 1) Community health 2) Revenue concentration risk "
                    "3) Growth opportunities 4) Retention red flags "
                    "5) Content strategy implications based on tenure distribution"
                ),
            },
            indent=2,
        )
