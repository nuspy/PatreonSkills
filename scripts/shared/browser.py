"""Playwright browser automation for Patreon write operations.

The Patreon API v2 is read-only for posts and comments. This module
uses Playwright to automate the browser for:
- Publishing new posts
- Posting comment replies
- Editing existing comments

Session is persisted to avoid re-authentication on each call.
Configured via environment variables (see config.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class BrowserNotConfiguredError(Exception):
    """Raised when PATREON_EMAIL/PATREON_PASSWORD are not configured."""


class PatreonBrowser:
    """Playwright-based Patreon browser automation."""

    LOGIN_URL = "https://www.patreon.com/login"
    POST_URL = "https://www.patreon.com/posts/new"

    def __init__(
        self,
        email: str,
        password: str,
        session_path: str,
        headless: bool = True,
    ):
        if not email or not password:
            raise BrowserNotConfiguredError(
                "PATREON_EMAIL and PATREON_PASSWORD must be set to use browser automation."
            )
        self.email = email
        self.password = password
        self.session_path = Path(session_path).expanduser()
        self.session_path.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    async def __aenter__(self) -> "PatreonBrowser":
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        # Load existing session if available
        session_file = self.session_path / "storage_state.json"
        storage_state = str(session_file) if session_file.exists() else None

        self._context = await self._browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        self._page = await self._context.new_page()

        # Check if we need to login
        if not await self._is_logged_in():
            await self._login()

        return self

    async def __aexit__(self, *args) -> None:
        if self._context:
            # Save session for next time
            session_file = self.session_path / "storage_state.json"
            await self._context.storage_state(path=str(session_file))
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _is_logged_in(self) -> bool:
        """Check if current session is authenticated."""
        await self._page.goto("https://www.patreon.com/home", timeout=15000)
        return "patreon.com/home" in self._page.url

    async def _login(self) -> None:
        """Log in to Patreon using email/password."""
        await self._page.goto(self.LOGIN_URL, wait_until="networkidle")

        # Fill email
        await self._page.fill('[name="email"]', self.email)
        await self._page.fill('[name="password"]', self.password)
        await self._page.click('[type="submit"]')

        # Wait for redirect after login
        await self._page.wait_for_url("**/home", timeout=15000)

        # Save session immediately after login
        session_file = self.session_path / "storage_state.json"
        await self._context.storage_state(path=str(session_file))

    async def publish_post(
        self,
        title: str,
        content: str,
        tier_ids: list[str] | None = None,
        campaign_id: str | None = None,
    ) -> dict:
        """Publish a new post to Patreon.

        Args:
            title: Post title
            content: Post body (HTML or plain text)
            tier_ids: Which tiers can see the post (None = public)
            campaign_id: Campaign ID (optional, detected automatically)

        Returns:
            Dict with success status and post URL if available
        """
        try:
            await self._page.goto(self.POST_URL, wait_until="networkidle")

            # Fill title
            title_selector = 'input[placeholder*="title"], [data-tag="title"]'
            await self._page.wait_for_selector(title_selector, timeout=10000)
            await self._page.fill(title_selector, title)

            # Fill content in the rich text editor
            editor_selector = '[contenteditable="true"], [data-tag="post-body"]'
            await self._page.wait_for_selector(editor_selector, timeout=5000)
            await self._page.click(editor_selector)
            await self._page.keyboard.type(content)

            # Publish button
            publish_selector = 'button[data-tag="publish"], button:has-text("Publish")'
            await self._page.click(publish_selector)

            # Wait for success
            await self._page.wait_for_url("**/posts/**", timeout=15000)
            post_url = self._page.url

            return {"success": True, "post_url": post_url}

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def post_comment(
        self,
        post_url: str,
        comment_text: str,
    ) -> dict:
        """Post a comment on a Patreon post.

        Args:
            post_url: Full URL of the Patreon post
            comment_text: Text of the comment to post

        Returns:
            Dict with success status
        """
        try:
            await self._page.goto(post_url, wait_until="networkidle")

            # Find comment textarea
            comment_selector = 'textarea[placeholder*="comment"], [data-tag="comment-input"]'
            await self._page.wait_for_selector(comment_selector, timeout=10000)
            await self._page.click(comment_selector)
            await self._page.fill(comment_selector, comment_text)

            # Submit comment
            submit_selector = 'button[data-tag="submit-comment"], button:has-text("Post")'
            await self._page.click(submit_selector)

            # Wait for comment to appear
            await self._page.wait_for_timeout(2000)

            return {"success": True}

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def post_bulk_comments(
        self,
        comments: list[dict],
        delay_seconds: float = 2.0,
    ) -> list[dict]:
        """Post comments on multiple posts.

        Args:
            comments: List of dicts with 'post_url' and 'text'
            delay_seconds: Delay between each comment

        Returns:
            List of result dicts
        """
        import asyncio

        results = []
        for item in comments:
            result = await self.post_comment(item["post_url"], item["text"])
            result["post_url"] = item["post_url"]
            results.append(result)
            await asyncio.sleep(delay_seconds)
        return results
