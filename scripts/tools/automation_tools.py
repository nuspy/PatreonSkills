"""Comment management and automation tools.

For fetching, analyzing, and responding to comments on Patreon posts.
Comment fetching uses web scraping (API doesn't expose comments).
Comment posting uses Playwright browser automation.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from scripts.shared.config import load_config
from scripts.shared.patreon_client import PatreonClient


def register(mcp: FastMCP) -> None:
    """Register automation and comment management tools."""

    @mcp.tool()
    async def comments_fetch_recent(
        campaign_id: str, max_posts: int = 5
    ) -> str:
        """
        Fetch recent posts and their visible comment metadata.
        Note: The Patreon API does not expose comments directly.
        This returns post data with a note about comment availability.

        Args:
            campaign_id: Patreon campaign ID
            max_posts: Number of recent posts to check
        """
        config = load_config()
        async with PatreonClient(config["access_token"]) as client:
            posts_data = await client.get_posts(campaign_id, count=max_posts)

        posts = [
            {
                "id": p.get("id"),
                "title": p.get("attributes", {}).get("title", ""),
                "url": p.get("attributes", {}).get("url", ""),
                "published_at": p.get("attributes", {}).get("published_at"),
                "patron_count": p.get("attributes", {}).get("patron_count", 0),
            }
            for p in posts_data.get("data", [])
        ]

        return json.dumps(
            {
                "campaign_id": campaign_id,
                "recent_posts": posts,
                "note": (
                    "The Patreon API does not expose comment content. "
                    "To see and respond to comments, use the post URLs above "
                    "and call comments_bulk_respond with the post URL and your response text."
                ),
                "next_step": "Use comments_generate_response to draft responses, then comments_bulk_respond to post them.",
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def comments_generate_response(
        comment_text: str,
        post_title: str = "",
        campaign_id: str = "",
        use_knowledge_base: bool = True,
    ) -> str:
        """
        Generate a context-aware response to a patron comment using RAG.
        Searches the knowledge base for relevant context, then returns
        a structured prompt for your agent model to generate the response.

        Args:
            comment_text: The patron's comment to respond to
            post_title: Optional title of the post being commented on
            campaign_id: Optional campaign ID for additional context
            use_knowledge_base: Whether to search the local knowledge base
        """
        config = load_config()

        # RAG retrieval
        rag_context = []
        if use_knowledge_base:
            try:
                from scripts.shared.rag import RAGManager
                rag = RAGManager(config["knowledge_base_path"])
                results = rag.search(
                    query=comment_text,
                    n_results=3,
                    min_score=0.4,
                )
                rag_context = [
                    {
                        "text": r["text"][:300],
                        "source": r.get("metadata", {}).get("source", ""),
                        "score": r["score"],
                        "collection": r["collection"],
                    }
                    for r in results
                ]
            except Exception:
                pass  # RAG not initialized, continue without it

        rag_section = ""
        if rag_context:
            rag_section = (
                f"\n\nRelevant context from knowledge base:\n"
                + "\n".join(f"- {r['text']}" for r in rag_context)
            )

        return json.dumps(
            {
                "comment": comment_text,
                "post_title": post_title,
                "rag_context_found": len(rag_context),
                "rag_context": rag_context,
                "response_prompt": (
                    f"You are a Patreon creator responding to a patron comment. "
                    f"Be warm, appreciative, and on-brand.\n\n"
                    f"Post: '{post_title}'\n"
                    f"Patron comment: '{comment_text}'"
                    f"{rag_section}\n\n"
                    "Write a natural, engaging 2-4 sentence response that:\n"
                    "1) Acknowledges what the patron said\n"
                    "2) Adds value or further engagement\n"
                    "3) Makes the patron feel seen and appreciated\n"
                    "Do NOT be sycophantic or generic. Be specific to their comment."
                ),
            },
            indent=2,
        )

    @mcp.tool()
    async def comments_bulk_respond(
        comments_json: str,
        delay_seconds: float = 3.0,
    ) -> str:
        """
        Post responses to multiple Patreon comments via browser automation.
        Requires PATREON_EMAIL and PATREON_PASSWORD.
        The Patreon API does not support comment management.

        Args:
            comments_json: JSON array of objects with 'post_url' and 'text' fields
                           Example: '[{"post_url": "https://...", "text": "Thanks!"}]'
            delay_seconds: Seconds between each comment post (default 3, min 1)
        """
        config = load_config()

        email = config.get("patreon_email", "")
        password = config.get("patreon_password", "")

        if not email or not password:
            return json.dumps(
                {
                    "success": False,
                    "error": "Browser automation not configured. Set PATREON_EMAIL and PATREON_PASSWORD.",
                },
                indent=2,
            )

        try:
            comments = json.loads(comments_json)
            if not isinstance(comments, list):
                raise ValueError("Expected a JSON array")
        except (json.JSONDecodeError, ValueError) as e:
            return json.dumps({"success": False, "error": f"Invalid JSON: {e}"}, indent=2)

        if len(comments) > 50:
            return json.dumps(
                {"success": False, "error": "Max 50 comments per batch"}, indent=2
            )

        from scripts.shared.browser import PatreonBrowser

        async with PatreonBrowser(
            email=email,
            password=password,
            session_path=config["browser_session_path"],
            headless=config["browser_headless"],
        ) as browser:
            results = await browser.post_bulk_comments(
                comments, delay_seconds=max(delay_seconds, 1.0)
            )

        successful = sum(1 for r in results if r.get("success"))
        failed = len(results) - successful

        return json.dumps(
            {
                "total": len(results),
                "successful": successful,
                "failed": failed,
                "results": results,
            },
            indent=2,
        )

    @mcp.tool()
    async def comments_analyze_sentiment(
        comments_json: str,
    ) -> str:
        """
        Prepare a batch of comments for sentiment analysis by your agent model.
        Returns comments + a structured prompt for classification.

        Args:
            comments_json: JSON array of comment strings or objects with 'text' field
                           Example: '["Great post!", "When is the next update?"]'
        """
        try:
            raw = json.loads(comments_json)
        except (json.JSONDecodeError, TypeError) as e:
            return json.dumps({"error": f"Invalid JSON: {e}"}, indent=2)

        # Normalize to list of strings
        if isinstance(raw, list):
            comments = [
                c.get("text", c) if isinstance(c, dict) else str(c)
                for c in raw
            ]
        else:
            return json.dumps({"error": "Expected a JSON array"}, indent=2)

        numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(comments))

        return json.dumps(
            {
                "comment_count": len(comments),
                "comments": comments,
                "sentiment_prompt": (
                    f"Analyze the sentiment of these {len(comments)} Patreon patron comments. "
                    "For each, classify as positive/neutral/negative and identify the main theme.\n\n"
                    f"{numbered}\n\n"
                    f"Return a JSON array with {len(comments)} objects, each with:\n"
                    "- \"index\": comment number\n"
                    "- \"sentiment\": \"positive\"|\"neutral\"|\"negative\"\n"
                    "- \"theme\": brief topic (e.g., 'appreciation', 'question', 'feedback', 'complaint')\n"
                    "- \"priority\": \"high\"|\"medium\"|\"low\" (how important to respond)\n\n"
                    "Then provide a summary: overall sentiment breakdown and top themes."
                ),
                "llm_batch_available": False,  # Set to True if LLM_BASE_URL configured
            },
            indent=2,
        )
