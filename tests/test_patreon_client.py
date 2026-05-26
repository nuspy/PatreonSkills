"""Tests for scripts/shared/patreon_client.py.

All HTTP calls are intercepted at the httpx.AsyncClient.request level
using unittest.mock so no real network traffic is generated.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scripts.shared.patreon_client import (
    PATREON_API_BASE,
    PatreonClient,
    PatreonError,
    WEBHOOK_EVENTS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resp(status: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    """Build a mock httpx.Response."""
    r = MagicMock()
    r.status_code = status
    r.text = text
    if json_data is not None:
        r.json.return_value = json_data
    return r


# ── PatreonError ──────────────────────────────────────────────────────────────


class TestPatreonError:
    def test_basic_creation(self):
        e = PatreonError(404, "Not found")
        assert e.status_code == 404
        assert "404" in str(e)
        assert e.errors == []

    def test_with_errors_list(self):
        errors = [{"detail": "Something went wrong", "status": "500"}]
        e = PatreonError(500, "Server error", errors=errors)
        assert e.errors[0]["detail"] == "Something went wrong"

    def test_is_exception(self):
        e = PatreonError(403, "Forbidden")
        assert isinstance(e, Exception)


# ── PatreonClient init & context manager ──────────────────────────────────────


class TestPatreonClientInit:
    def test_stores_access_token(self):
        c = PatreonClient("pat_abc123")
        assert c.access_token == "pat_abc123"
        assert c._client is None

    async def test_context_manager_creates_http_client(self):
        async with PatreonClient("pat_test") as c:
            assert isinstance(c._client, httpx.AsyncClient)

    async def test_uninitialized_request_raises(self):
        c = PatreonClient("pat_test")
        with pytest.raises(RuntimeError, match="context manager"):
            await c._request("GET", "/identity")


# ── Successful API responses ───────────────────────────────────────────────────


class TestSuccessfulRequests:
    async def test_get_identity(self):
        data = {
            "data": {
                "id": "user_1",
                "type": "user",
                "attributes": {"full_name": "Alice Creator", "email": "alice@example.com"},
            }
        }
        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=_resp(200, data)
        ):
            async with PatreonClient("pat_test") as c:
                result = await c.get_identity()

        assert result["data"]["id"] == "user_1"
        assert result["data"]["attributes"]["full_name"] == "Alice Creator"

    async def test_get_campaigns(self):
        data = {
            "data": [
                {
                    "id": "campaign_1",
                    "type": "campaign",
                    "attributes": {"patron_count": 250, "pledge_sum": 75000},
                }
            ]
        }
        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=_resp(200, data)
        ):
            async with PatreonClient("pat_test") as c:
                result = await c.get_campaigns()

        assert len(result["data"]) == 1
        assert result["data"][0]["attributes"]["patron_count"] == 250

    async def test_delete_returns_empty_dict_on_204(self):
        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=_resp(204)
        ):
            async with PatreonClient("pat_test") as c:
                result = await c.delete_webhook("wh_abc")

        assert result == {}


# ── Error handling ─────────────────────────────────────────────────────────────


class TestErrorHandling:
    async def test_404_raises_patreon_error(self):
        body = {"errors": [{"detail": "Campaign not found", "status": "404"}]}
        with patch.object(
            httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=_resp(404, body)
        ):
            async with PatreonClient("pat_test") as c:
                with pytest.raises(PatreonError) as exc:
                    await c.get_campaign("nonexistent")

        assert exc.value.status_code == 404

    async def test_401_raises_patreon_error(self):
        with patch.object(
            httpx.AsyncClient,
            "request",
            new_callable=AsyncMock,
            return_value=_resp(401, text="Unauthorized"),
        ):
            async with PatreonClient("bad_token") as c:
                with pytest.raises(PatreonError) as exc:
                    await c.get_identity()

        assert exc.value.status_code == 401

    async def test_rate_limit_retries_then_succeeds(self):
        data = {"data": {"id": "u1", "type": "user", "attributes": {"full_name": "Bob"}}}
        responses = [_resp(429, text="Too Many Requests"), _resp(200, data)]
        mock_req = AsyncMock(side_effect=responses)

        with patch.object(httpx.AsyncClient, "request", mock_req):
            with patch(
                "scripts.shared.patreon_client.asyncio.sleep", new_callable=AsyncMock
            ):
                async with PatreonClient("pat_test") as c:
                    result = await c.get_identity()

        assert mock_req.call_count == 2
        assert result["data"]["id"] == "u1"


# ── Pagination ────────────────────────────────────────────────────────────────


class TestPagination:
    async def test_get_all_members_follows_cursor(self):
        page1 = {
            "data": [
                {"id": "m1", "type": "member"},
                {"id": "m2", "type": "member"},
            ],
            "meta": {"pagination": {"cursors": {"next": "cursor_page2"}}},
        }
        page2 = {
            "data": [{"id": "m3", "type": "member"}],
            "meta": {"pagination": {"cursors": {}}},  # no next cursor
        }
        mock_req = AsyncMock(side_effect=[_resp(200, page1), _resp(200, page2)])

        with patch.object(httpx.AsyncClient, "request", mock_req):
            with patch(
                "scripts.shared.patreon_client.asyncio.sleep", new_callable=AsyncMock
            ):
                async with PatreonClient("pat_test") as c:
                    members = [m async for m in c.get_all_members("campaign_1")]

        assert len(members) == 3
        assert members[0]["id"] == "m1"
        assert members[2]["id"] == "m3"
        assert mock_req.call_count == 2

    async def test_get_all_posts_stops_on_empty_page(self):
        page_empty = {
            "data": [],
            "meta": {"pagination": {"cursors": {"next": "cursor_orphan"}}},
        }
        mock_req = AsyncMock(return_value=_resp(200, page_empty))

        with patch.object(httpx.AsyncClient, "request", mock_req):
            with patch(
                "scripts.shared.patreon_client.asyncio.sleep", new_callable=AsyncMock
            ):
                async with PatreonClient("pat_test") as c:
                    posts = [p async for p in c.get_all_posts("campaign_1")]

        assert posts == []
        assert mock_req.call_count == 1


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_patreon_api_base_is_string(self):
        assert isinstance(PATREON_API_BASE, str)
        assert "patreon.com" in PATREON_API_BASE

    def test_webhook_events_not_empty(self):
        assert len(WEBHOOK_EVENTS) > 0
        assert all(isinstance(e, str) for e in WEBHOOK_EVENTS)
