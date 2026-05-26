"""Content analysis and post generation tools.

Tools for analyzing your post history, generating content drafts,
creating media prompts, and managing the content calendar.

AI generation tools return structured prompts for the calling agent's model.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from scripts.shared.config import load_config
from scripts.shared.patreon_client import PatreonClient


def register(mcp: FastMCP) -> None:
    """Register content tools."""

    @mcp.tool()
    async def posts_get_analytics(campaign_id: str) -> str:
        """
        Analyze post history: post types breakdown, posting frequency,
        most recent posts, average patron count per post type.
        Useful for understanding what content resonates.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        posts = []

        async with PatreonClient(config["access_token"]) as client:
            async for p in client.get_all_posts(campaign_id):
                a = p.get("attributes", {})
                posts.append(
                    {
                        "id": p.get("id"),
                        "title": a.get("title", ""),
                        "type": a.get("post_type", "text_only"),
                        "published_at": a.get("published_at"),
                        "patron_count": a.get("patron_count", 0),
                        "is_paid": a.get("is_paid", False),
                        "url": a.get("url", ""),
                    }
                )

        if not posts:
            return json.dumps({"campaign_id": campaign_id, "posts": [], "total": 0})

        # Post type distribution
        type_counter: Counter = Counter(p["type"] for p in posts)
        patron_by_type: dict = {}
        for ptype in type_counter:
            typed_posts = [p for p in posts if p["type"] == ptype]
            avg_patrons = sum(p["patron_count"] for p in typed_posts) / len(typed_posts)
            patron_by_type[ptype] = round(avg_patrons, 1)

        # Posting frequency
        dated = [
            p for p in posts if p["published_at"]
        ]
        if len(dated) >= 2:
            dates = sorted(p["published_at"] for p in dated)
            try:
                first = datetime.fromisoformat(dates[0].replace("Z", "+00:00"))
                last = datetime.fromisoformat(dates[-1].replace("Z", "+00:00"))
                months = max((last - first).days / 30.44, 1)
                posts_per_month = round(len(posts) / months, 1)
            except Exception:
                posts_per_month = None
        else:
            posts_per_month = None

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "total_posts": len(posts),
                "posts_per_month": posts_per_month,
                "post_type_distribution": dict(type_counter),
                "avg_patron_count_by_type": patron_by_type,
                "recent_posts": posts[:10],
                "paid_posts": sum(1 for p in posts if p["is_paid"]),
                "free_posts": sum(1 for p in posts if not p["is_paid"]),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def posts_fetch_content(post_id: str) -> str:
        """
        Retrieve full content of a specific post by ID.
        Useful for analyzing past content or using it as reference for new posts.

        Args:
            post_id: Patreon post ID
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            post = await client.get_post(post_id)

        p = post.get("data", {})
        a = p.get("attributes", {})

        return json.dumps(
            {
                "id": p.get("id"),
                "title": a.get("title"),
                "content": a.get("content", ""),
                "teaser_text": a.get("teaser_text", ""),
                "post_type": a.get("post_type"),
                "published_at": a.get("published_at"),
                "is_paid": a.get("is_paid"),
                "patron_count": a.get("patron_count", 0),
                "url": a.get("url"),
                "thumbnail_url": a.get("thumbnail_url"),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def posts_generate_draft(
        campaign_id: str,
        topic: str,
        post_type: str = "article",
        tone: str = "engaging",
        target_tier: str = "all",
        reference_post_ids: str = "",
    ) -> str:
        """
        Build a rich prompt for generating a Patreon post draft.
        Returns the 'generation_prompt' field to pass to your model.

        Args:
            campaign_id: Patreon campaign ID
            topic: What the post should be about
            post_type: 'article' | 'update' | 'exclusive' | 'poll' | 'behind_scenes'
            tone: 'engaging' | 'professional' | 'casual' | 'inspiring' | 'funny'
            target_tier: Tier this post is for ('all', 'premium', etc.)
            reference_post_ids: Comma-separated post IDs to use as style reference
        """
        config = load_config()

        # Fetch campaign context
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

            # Fetch reference posts if provided
            ref_content = []
            if reference_post_ids:
                for pid in reference_post_ids.split(",")[:3]:
                    pid = pid.strip()
                    if pid:
                        try:
                            post = await client.get_post(pid)
                            a = post.get("data", {}).get("attributes", {})
                            ref_content.append(
                                f"Title: {a.get('title', '')}\nContent: {(a.get('content') or '')[:400]}"
                            )
                        except Exception:
                            pass

        ca = campaign.get("data", {}).get("attributes", {})

        ref_section = ""
        if ref_content:
            ref_section = f"\n\nReference posts (match this style):\n" + "\n---\n".join(ref_content)

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "topic": topic,
                "post_type": post_type,
                "tone": tone,
                "target_tier": target_tier,
                "creation_name": ca.get("creation_name"),
                "generation_prompt": (
                    f"Write a Patreon {post_type} post for creator '{ca.get('creation_name')}'.\n"
                    f"Topic: {topic}\n"
                    f"Tone: {tone}\n"
                    f"Audience: {target_tier} tier patrons\n"
                    f"Creator summary: {(ca.get('summary') or '')[:300]}"
                    f"{ref_section}\n\n"
                    "Structure the post with:\n"
                    "1. Hook (first 2 sentences that grab attention)\n"
                    "2. Main content (detailed, valuable, on-topic)\n"
                    "3. Exclusive element (something special for patrons)\n"
                    "4. Call-to-action (engage, comment, share)\n\n"
                    "Also provide a catchy title and a 1-sentence teaser text."
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def posts_generate_with_media(
        campaign_id: str,
        topic: str,
        media_type: str = "image",
        style: str = "",
    ) -> str:
        """
        Generate a post draft prompt + media generation prompts.
        The 'image_prompts' and 'video_prompts' can be passed to
        image/video generation skills (e.g., Stable Diffusion, DALL-E, Sora).

        Args:
            campaign_id: Patreon campaign ID
            topic: Post topic
            media_type: 'image' | 'video' | 'both'
            style: Optional visual style description (e.g., 'anime', 'photorealistic', 'watercolor')
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)

        ca = campaign.get("data", {}).get("attributes", {})
        creation_name = ca.get("creation_name", "")

        result: dict = {
            "campaign_id": campaign_id,
            "topic": topic,
            "creation_name": creation_name,
            "post_prompt": (
                f"Write a Patreon post for '{creation_name}' about: {topic}. "
                "Include a compelling title, engaging body text, and a call-to-action."
            ),
        }

        if media_type in ("image", "both"):
            result["image_prompts"] = [
                f"High quality illustration for Patreon post about '{topic}', {style or 'professional'} style, engaging, suitable for social media, 16:9 aspect ratio",
                f"Thumbnail image for '{topic}' Patreon content, {style or 'vibrant'}, eye-catching, text overlay space at bottom",
                f"Behind the scenes photo style image related to '{topic}' for Patreon community",
            ]

        if media_type in ("video", "both"):
            result["video_script_prompt"] = (
                f"Write a 60-90 second video script for a Patreon exclusive about '{topic}'. "
                f"Creator: {creation_name}. Style: personal, engaging, makes patrons feel valued. "
                "Include intro hook, main content, and patron appreciation outro."
            )
            result["video_prompts"] = [
                f"Short-form video about {topic}, creator style, engaging storytelling, {style or 'cinematic'} look",
            ]

        return json.dumps(result, indent=2, default=str)

    @mcp.tool()
    async def posts_optimize_for_engagement(
        campaign_id: str, post_content: str, post_title: str = ""
    ) -> str:
        """
        Return post content + context for AI-powered engagement optimization.
        The 'optimization_prompt' is ready to pass to your agent model.

        Args:
            campaign_id: Patreon campaign ID
            post_content: The post body to optimize
            post_title: Optional current post title
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            posts_data = await client.get_posts(campaign_id, count=5)

        recent_titles = [
            p.get("attributes", {}).get("title", "")
            for p in posts_data.get("data", [])
        ]

        return json.dumps(
            {
                "current_title": post_title,
                "current_content_length": len(post_content),
                "recent_post_titles": recent_titles,
                "optimization_prompt": (
                    f"Improve this Patreon post for maximum patron engagement:\n\n"
                    f"TITLE: {post_title or '(no title)'}\n\n"
                    f"CONTENT:\n{post_content[:2000]}\n\n"
                    "Recent posts by this creator: " + ", ".join(f"'{t}'" for t in recent_titles if t) + "\n\n"
                    "Provide: 1) Improved title options (3 variants) "
                    "2) Rewritten opening paragraph (stronger hook) "
                    "3) Suggestions to add exclusivity/value for patrons "
                    "4) Better call-to-action "
                    "5) Optimal post length recommendation"
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def posts_suggest_content_calendar(
        campaign_id: str,
        weeks: int = 4,
        niche: str = "",
        posts_per_week: int = 2,
    ) -> str:
        """
        Analyze posting history and return a prompt for generating a content calendar.
        Pass 'calendar_prompt' to your model to get a week-by-week posting plan.

        Args:
            campaign_id: Patreon campaign ID
            weeks: How many weeks to plan (default 4)
            niche: Creator niche for context
            posts_per_week: Target posting frequency
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            posts_data = await client.get_posts(campaign_id, count=20)

        ca_data = await _get_campaign_name(config, campaign_id)

        recent = [
            {
                "title": p.get("attributes", {}).get("title", ""),
                "type": p.get("attributes", {}).get("post_type", ""),
                "date": p.get("attributes", {}).get("published_at", ""),
            }
            for p in posts_data.get("data", [])[:10]
        ]

        type_counts = Counter(p["type"] for p in recent)

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "creation_name": ca_data,
                "niche": niche,
                "recent_content_types": dict(type_counts),
                "recent_titles": [p["title"] for p in recent if p["title"]],
                "calendar_prompt": (
                    f"Create a {weeks}-week Patreon content calendar for '{ca_data}' "
                    f"({niche or 'general creator'}).\n"
                    f"Target: {posts_per_week} posts/week.\n"
                    f"Recent post types: {dict(type_counts)}\n"
                    f"Recent titles: {[p['title'] for p in recent[:5] if p['title']]}\n\n"
                    "For each week provide:\n"
                    "- Post 1: Type, title idea, target tier, key content points\n"
                    "- Post 2: Type, title idea, target tier, key content points\n"
                    "Mix: exclusive content, updates, behind-the-scenes, community posts.\n"
                    "Vary post types to avoid repetition."
                ),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def posts_draft_and_review(
        title: str,
        content: str,
        teaser_text: str = "",
        target_tier_ids: str = "",
        scheduled_for: str = "",
    ) -> str:
        """
        Prepare a post draft for review before publishing.
        Returns a structured preview of the post ready to be published
        via posts_publish_via_browser.

        Args:
            title: Post title
            content: Post body text (markdown/HTML supported)
            teaser_text: Short preview for non-patrons (optional)
            target_tier_ids: Comma-separated tier IDs (empty = all tiers)
            scheduled_for: ISO8601 datetime to schedule (empty = publish now)
        """
        word_count = len(content.split())
        char_count = len(content)
        read_time = max(1, round(word_count / 200))

        return json.dumps(
            {
                "status": "draft_ready",
                "post": {
                    "title": title,
                    "content_preview": content[:500] + ("..." if len(content) > 500 else ""),
                    "full_content_length": char_count,
                    "word_count": word_count,
                    "estimated_read_time_minutes": read_time,
                    "teaser_text": teaser_text,
                    "target_tier_ids": [t.strip() for t in target_tier_ids.split(",") if t.strip()],
                    "scheduled_for": scheduled_for or "immediate",
                },
                "next_step": "Call posts_publish_via_browser with this content to publish.",
            },
            indent=2,
        )

    @mcp.tool()
    async def posts_publish_via_browser(
        title: str,
        content: str,
        campaign_id: str = "",
    ) -> str:
        """
        Publish a post to Patreon using browser automation (Playwright).
        Requires PATREON_EMAIL and PATREON_PASSWORD environment variables.
        The Patreon API does not support post creation — this uses the web interface.

        Args:
            title: Post title
            content: Post body text
            campaign_id: Optional campaign ID for logging
        """
        config = load_config()

        email = config.get("patreon_email", "")
        password = config.get("patreon_password", "")

        if not email or not password:
            return json.dumps(
                {
                    "success": False,
                    "error": "Browser automation not configured. Set PATREON_EMAIL and PATREON_PASSWORD.",
                    "hint": "Add these to your .env file to enable auto-publishing.",
                },
                indent=2,
            )

        from scripts.shared.browser import PatreonBrowser

        async with PatreonBrowser(
            email=email,
            password=password,
            session_path=config["browser_session_path"],
            headless=config["browser_headless"],
        ) as browser:
            result = await browser.publish_post(title=title, content=content)

        return json.dumps(result, indent=2)


async def _get_campaign_name(config: dict, campaign_id: str) -> str:
    """Helper to get campaign creation name."""
    try:
        async with PatreonClient(config["access_token"]) as client:
            campaigns = await client.get_campaigns(include_tiers=False)
        for c in campaigns.get("data", []):
            if c.get("id") == campaign_id:
                return c.get("attributes", {}).get("creation_name", "")
    except Exception:
        pass
    return ""
