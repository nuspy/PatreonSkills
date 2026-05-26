"""Patreon API v2 async client.

Provides full access to the Patreon API v2 with:
- Cursor-based pagination helpers
- Automatic retry with exponential backoff
- Rate limit handling (HTTP 429)
- Explicit field selection (Patreon returns nothing by default)
"""

import asyncio
from typing import Any, AsyncGenerator

import httpx

PATREON_API_BASE = "https://www.patreon.com/api/oauth2/v2"

# ── Default field sets per resource ──
CAMPAIGN_FIELDS = (
    "summary,creation_name,patron_count,pledge_sum,main_video_url,"
    "image_url,image_small_url,thanks_msg,one_liner,created_at,"
    "published_at,is_monthly,is_nsfw,url"
)
MEMBER_FIELDS = (
    "full_name,email,patron_status,charge_status,"
    "currently_entitled_amount_cents,lifetime_support_cents,"
    "campaign_lifetime_support_cents,last_charge_date,last_charge_status,"
    "pledge_relationship_start,next_charge_date,note,will_pay_amount_cents"
)
TIER_FIELDS = (
    "amount_cents,user_count,description,created_at,published_at,"
    "title,tier_type,patron_count,post_count,discord_role_ids,image_url,url"
)
POST_FIELDS = (
    "title,content,embed_data,url,teaser_text,is_paid,"
    "min_cents_pledged_to_view,patron_count,published_at,"
    "post_type,thumbnail_url"
)
USER_FIELDS = (
    "about,created,email,first_name,full_name,image_url,"
    "last_name,social_connections,thumb_url,url,vanity"
)
GOAL_FIELDS = (
    "amount_cents,completed_percentage,created_at,description,reached_at,title"
)
BENEFIT_FIELDS = (
    "title,description,benefit_type,rule_type,is_recurring,"
    "is_deleted,created_at,deliverables_due_today_count,"
    "delivered_deliverables_count,not_delivered_deliverables_count,"
    "next_deliverable_due_date"
)

# Patreon webhook events
WEBHOOK_EVENTS = [
    "members:create",
    "members:update",
    "members:delete",
    "members:pledge:create",
    "members:pledge:update",
    "members:pledge:delete",
    "posts:publish",
    "posts:update",
    "posts:delete",
]


class PatreonError(Exception):
    """Raised when the Patreon API returns an error response."""

    def __init__(self, status_code: int, message: str, errors: list | None = None):
        self.status_code = status_code
        self.errors = errors or []
        super().__init__(f"Patreon API error {status_code}: {message}")


class PatreonClient:
    """Async Patreon API v2 client.

    Usage:
        async with PatreonClient(access_token) as client:
            identity = await client.get_identity()
    """

    def __init__(self, access_token: str):
        self.access_token = access_token
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PatreonClient":
        self._client = httpx.AsyncClient(
            base_url=PATREON_API_BASE,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "User-Agent": "patreon-creator-skill/1.0",
            },
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        payload: dict | None = None,
        max_retries: int = 3,
    ) -> dict:
        """Execute an API request with retry logic and rate limit handling."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use as async context manager.")

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = await self._client.request(
                    method, path, params=params, json=payload
                )

                if response.status_code == 429:
                    # Rate limited — exponential backoff
                    wait = 2 ** (attempt + 1)
                    await asyncio.sleep(wait)
                    continue

                if response.status_code == 204:
                    # No content (DELETE success)
                    return {}

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        errors = error_data.get("errors", [])
                        message = (
                            errors[0].get("detail", "Unknown error")
                            if errors
                            else response.text
                        )
                    except Exception:
                        message = response.text
                    raise PatreonError(
                        response.status_code, message, errors if "errors" in dir() else []
                    )

                return response.json()

            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise PatreonError(408, f"Request timed out after {max_retries} attempts")

    # ───────────────────────────────────────────────────────────────
    # Identity
    # ───────────────────────────────────────────────────────────────

    async def get_identity(self, include_campaigns: bool = True) -> dict:
        """Get authenticated user's identity."""
        params: dict = {"fields[user]": USER_FIELDS}
        if include_campaigns:
            params["include"] = "memberships,campaign"
            params["fields[campaign]"] = "summary,creation_name,patron_count,pledge_sum,url"
        return await self._request("GET", "/identity", params=params)

    # ───────────────────────────────────────────────────────────────
    # Campaigns
    # ───────────────────────────────────────────────────────────────

    async def get_campaigns(
        self,
        include_tiers: bool = True,
        include_benefits: bool = False,
    ) -> dict:
        """Get all campaigns for the authenticated creator."""
        includes: list[str] = []
        params: dict = {"fields[campaign]": CAMPAIGN_FIELDS}

        if include_tiers:
            includes.append("tiers")
            params["fields[tier]"] = TIER_FIELDS
        if include_benefits:
            includes.append("benefits")
            params["fields[benefit]"] = BENEFIT_FIELDS

        if includes:
            params["include"] = ",".join(includes)

        return await self._request("GET", "/campaigns", params=params)

    async def get_campaign(self, campaign_id: str) -> dict:
        """Get full details for a specific campaign including tiers, benefits, goals."""
        params = {
            "fields[campaign]": CAMPAIGN_FIELDS,
            "include": "tiers,benefits,goals,creator",
            "fields[tier]": TIER_FIELDS,
            "fields[benefit]": BENEFIT_FIELDS,
            "fields[goal]": GOAL_FIELDS,
            "fields[user]": "full_name,vanity,url,image_url",
        }
        return await self._request("GET", f"/campaigns/{campaign_id}", params=params)

    # ───────────────────────────────────────────────────────────────
    # Members
    # ───────────────────────────────────────────────────────────────

    async def get_members(
        self,
        campaign_id: str,
        count: int = 1000,
        cursor: str | None = None,
        include_tiers: bool = True,
        include_user: bool = False,
    ) -> dict:
        """Get a page of campaign members."""
        params: dict = {
            "fields[member]": MEMBER_FIELDS,
            "page[count]": count,
        }
        if cursor:
            params["page[cursor]"] = cursor

        includes: list[str] = []
        if include_tiers:
            includes.append("currently_entitled_tiers")
            params["fields[tier]"] = "title,amount_cents,tier_type"
        if include_user:
            includes.append("user")
            params["fields[user]"] = "full_name,image_url,url"
        if includes:
            params["include"] = ",".join(includes)

        return await self._request(
            "GET", f"/campaigns/{campaign_id}/members", params=params
        )

    async def get_all_members(
        self, campaign_id: str
    ) -> AsyncGenerator[dict, None]:
        """Async generator yielding all members with automatic cursor pagination."""
        cursor: str | None = None

        while True:
            page = await self.get_members(campaign_id, count=1000, cursor=cursor)
            members = page.get("data", [])

            for member in members:
                yield member

            meta = page.get("meta", {})
            next_cursor = (
                meta.get("pagination", {})
                .get("cursors", {})
                .get("next")
            )
            if not next_cursor or not members:
                break
            cursor = next_cursor
            # Small delay to respect rate limits
            await asyncio.sleep(0.5)

    async def get_member(self, member_id: str) -> dict:
        """Get details for a specific member."""
        params = {
            "fields[member]": MEMBER_FIELDS,
            "include": "currently_entitled_tiers,user",
            "fields[tier]": TIER_FIELDS,
            "fields[user]": USER_FIELDS,
        }
        return await self._request("GET", f"/members/{member_id}", params=params)

    # ───────────────────────────────────────────────────────────────
    # Posts
    # ───────────────────────────────────────────────────────────────

    async def get_posts(
        self,
        campaign_id: str,
        count: int = 20,
        cursor: str | None = None,
    ) -> dict:
        """Get a page of campaign posts."""
        params: dict = {
            "fields[post]": POST_FIELDS,
            "page[count]": count,
        }
        if cursor:
            params["page[cursor]"] = cursor
        return await self._request(
            "GET", f"/campaigns/{campaign_id}/posts", params=params
        )

    async def get_all_posts(
        self, campaign_id: str
    ) -> AsyncGenerator[dict, None]:
        """Async generator yielding all posts with automatic cursor pagination."""
        cursor: str | None = None

        while True:
            page = await self.get_posts(campaign_id, count=20, cursor=cursor)
            posts = page.get("data", [])

            for post in posts:
                yield post

            next_cursor = (
                page.get("meta", {})
                .get("pagination", {})
                .get("cursors", {})
                .get("next")
            )
            if not next_cursor or not posts:
                break
            cursor = next_cursor
            await asyncio.sleep(0.2)

    async def get_post(self, post_id: str) -> dict:
        """Get details for a specific post."""
        params = {
            "fields[post]": POST_FIELDS,
            "include": "campaign,user",
            "fields[user]": "full_name,image_url",
        }
        return await self._request("GET", f"/posts/{post_id}", params=params)

    # ───────────────────────────────────────────────────────────────
    # Webhooks
    # ───────────────────────────────────────────────────────────────

    async def list_webhooks(self, campaign_id: str) -> dict:
        """List all webhooks for a campaign."""
        return await self._request(
            "GET", f"/campaigns/{campaign_id}/webhook_subscriptions"
        )

    async def create_webhook(
        self,
        campaign_id: str,
        url: str,
        events: list[str],
    ) -> dict:
        """Create a new webhook subscription."""
        payload = {
            "data": {
                "type": "webhook",
                "attributes": {
                    "triggers": events,
                    "uri": url,
                    "paused": False,
                },
                "relationships": {
                    "campaign": {
                        "data": {"type": "campaign", "id": campaign_id}
                    }
                },
            }
        }
        return await self._request("POST", "/webhooks", payload=payload)

    async def update_webhook(
        self,
        webhook_id: str,
        url: str | None = None,
        events: list[str] | None = None,
        paused: bool | None = None,
    ) -> dict:
        """Update a webhook subscription."""
        attributes: dict = {}
        if url is not None:
            attributes["uri"] = url
        if events is not None:
            attributes["triggers"] = events
        if paused is not None:
            attributes["paused"] = paused

        payload = {
            "data": {
                "type": "webhook",
                "id": webhook_id,
                "attributes": attributes,
            }
        }
        return await self._request("PATCH", f"/webhooks/{webhook_id}", payload=payload)

    async def delete_webhook(self, webhook_id: str) -> dict:
        """Delete a webhook subscription."""
        return await self._request("DELETE", f"/webhooks/{webhook_id}")
