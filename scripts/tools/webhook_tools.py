"""Webhook management tools.

Full CRUD for Patreon webhook subscriptions.
Webhooks are the only write-supported resource in the Patreon API.

Available webhook events:
  - members:create       New patron joins
  - members:update       Patron changes pledge
  - members:delete       Patron cancels
  - members:pledge:create  New pledge created
  - members:pledge:update  Pledge amount changed
  - members:pledge:delete  Pledge cancelled
  - posts:publish        New post published
  - posts:update         Post edited
  - posts:delete         Post deleted
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from scripts.shared.config import load_config
from scripts.shared.patreon_client import PatreonClient, WEBHOOK_EVENTS


def register(mcp: FastMCP) -> None:
    """Register webhook management tools."""

    @mcp.tool()
    async def webhooks_list(campaign_id: str) -> str:
        """
        List all webhook subscriptions for a campaign.

        Args:
            campaign_id: Patreon campaign ID
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            data = await client.list_webhooks(campaign_id)

        webhooks = [
            {
                "id": w.get("id"),
                "url": w.get("attributes", {}).get("uri"),
                "events": w.get("attributes", {}).get("triggers", []),
                "paused": w.get("attributes", {}).get("paused", False),
                "secret": w.get("attributes", {}).get("secret"),
                "last_attempted_at": w.get("attributes", {}).get("last_attempted_at"),
                "num_consecutive_times_failed": w.get("attributes", {}).get("num_consecutive_times_failed", 0),
            }
            for w in data.get("data", [])
        ]

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "webhook_count": len(webhooks),
                "webhooks": webhooks,
                "available_events": WEBHOOK_EVENTS,
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def webhooks_create(
        campaign_id: str,
        url: str,
        events: str,
    ) -> str:
        """
        Create a new webhook subscription for a campaign.
        Webhooks send POST requests to your URL when events occur.

        Args:
            campaign_id: Patreon campaign ID
            url: HTTPS endpoint to receive webhook payloads
            events: Comma-separated list of events to subscribe to.
                    Options: members:create, members:update, members:delete,
                    members:pledge:create, members:pledge:update, members:pledge:delete,
                    posts:publish, posts:update, posts:delete
        """
        config = load_config()
        event_list = [e.strip() for e in events.split(",") if e.strip()]

        # Validate events
        invalid = [e for e in event_list if e not in WEBHOOK_EVENTS]
        if invalid:
            return json.dumps(
                {
                    "error": f"Invalid events: {invalid}",
                    "valid_events": WEBHOOK_EVENTS,
                },
                indent=2,
            )

        async with PatreonClient(config["access_token"]) as client:
            data = await client.create_webhook(campaign_id, url, event_list)

        w = data.get("data", {})
        a = w.get("attributes", {})

        return json.dumps(
            {
                "success": True,
                "webhook_id": w.get("id"),
                "url": a.get("uri"),
                "events": a.get("triggers", []),
                "secret": a.get("secret"),
                "note": "Save the 'secret' to verify webhook payloads using HMAC-MD5.",
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def webhooks_update(
        webhook_id: str,
        url: str = "",
        events: str = "",
        paused: str = "",
    ) -> str:
        """
        Update an existing webhook subscription.
        Only provide the fields you want to change.

        Args:
            webhook_id: Webhook ID to update
            url: New endpoint URL (optional)
            events: New comma-separated event list (optional)
            paused: 'true' or 'false' to pause/unpause the webhook (optional)
        """
        config = load_config()

        event_list = [e.strip() for e in events.split(",") if e.strip()] if events else None
        paused_bool = None
        if paused:
            paused_bool = paused.lower() in ("true", "1", "yes")

        async with PatreonClient(config["access_token"]) as client:
            data = await client.update_webhook(
                webhook_id,
                url=url or None,
                events=event_list,
                paused=paused_bool,
            )

        w = data.get("data", {})
        a = w.get("attributes", {})

        return json.dumps(
            {
                "success": True,
                "webhook_id": w.get("id"),
                "url": a.get("uri"),
                "events": a.get("triggers", []),
                "paused": a.get("paused"),
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def webhooks_delete(webhook_id: str) -> str:
        """
        Delete a webhook subscription permanently.

        Args:
            webhook_id: Webhook ID to delete
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            await client.delete_webhook(webhook_id)

        return json.dumps(
            {"success": True, "webhook_id": webhook_id, "message": "Webhook deleted."},
            indent=2,
        )
