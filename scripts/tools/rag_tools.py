"""Knowledge base (RAG) management tools.

Manages a local ChromaDB knowledge base used for context-aware
comment responses, brand voice consistency, and FAQ management.

Collections:
  - posts: Your campaign post content
  - faqs: Frequently asked questions and answers
  - brand_voice: Brand voice guidelines and writing examples
  - custom_docs: Any other documents
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from scripts.shared.config import load_config
from scripts.shared.patreon_client import PatreonClient


def register(mcp: FastMCP) -> None:
    """Register knowledge base management tools."""

    @mcp.tool()
    async def kb_index_campaign(
        campaign_id: str, max_posts: int = 50
    ) -> str:
        """
        Index all campaign posts into the local knowledge base.
        This enables context-aware comment responses and content analysis.
        Run this once initially, then periodically to add new posts.

        Args:
            campaign_id: Patreon campaign ID to index
            max_posts: Maximum number of posts to index (default 50)
        """
        config = load_config()
        from scripts.shared.rag import RAGManager

        rag = RAGManager(config["knowledge_base_path"])
        indexed = 0
        errors = 0

        async with PatreonClient(config["access_token"]) as client:
            campaign = await client.get_campaign(campaign_id)
            ca = campaign.get("data", {}).get("attributes", {})

            docs = []
            async for post in client.get_all_posts(campaign_id):
                if indexed + len(docs) >= max_posts:
                    break

                a = post.get("attributes", {})
                title = a.get("title", "")
                content = a.get("content", "") or a.get("teaser_text", "")

                if not content and not title:
                    continue

                text = f"Title: {title}\n\n{content}" if content else title
                docs.append(
                    {
                        "id": f"post_{post.get('id')}",
                        "text": text[:2000],
                        "metadata": {
                            "source": "patreon_post",
                            "post_id": post.get("id"),
                            "title": title,
                            "published_at": a.get("published_at", ""),
                            "campaign_id": campaign_id,
                            "post_type": a.get("post_type", ""),
                        },
                    }
                )

        if docs:
            try:
                rag.add_documents_batch(docs, collection="posts")
                indexed = len(docs)
            except Exception as e:
                errors += 1
                return json.dumps(
                    {"success": False, "error": str(e)}, indent=2
                )

        stats = rag.get_stats()

        return json.dumps(
            {
                "success": True,
                "campaign_id": campaign_id,
                "creation_name": ca.get("creation_name"),
                "posts_indexed": indexed,
                "knowledge_base_stats": stats,
            },
            indent=2,
            default=str,
        )

    @mcp.tool()
    async def kb_add_document(
        text: str,
        collection: str = "custom_docs",
        title: str = "",
        source: str = "",
        tags: str = "",
    ) -> str:
        """
        Add a document to the local knowledge base.
        Useful for FAQs, brand voice guidelines, product info, etc.

        Args:
            text: Document content to index
            collection: 'posts' | 'faqs' | 'brand_voice' | 'custom_docs'
            title: Document title (optional, stored as metadata)
            source: Document source description (optional)
            tags: Comma-separated tags (optional)
        """
        config = load_config()
        from scripts.shared.rag import RAGManager

        rag = RAGManager(config["knowledge_base_path"])
        metadata = {
            "title": title,
            "source": source,
            "tags": tags,
        }

        try:
            doc_id = rag.add_document(text, collection=collection, metadata=metadata)
            stats = rag.get_stats()
            return json.dumps(
                {
                    "success": True,
                    "doc_id": doc_id,
                    "collection": collection,
                    "text_length": len(text),
                    "knowledge_base_stats": stats,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    @mcp.tool()
    async def kb_search(
        query: str,
        collections: str = "",
        n_results: int = 5,
        min_score: float = 0.3,
    ) -> str:
        """
        Semantic search in the local knowledge base.
        Searches all collections by default, or specific ones.

        Args:
            query: Search query
            collections: Comma-separated collection names to search, or empty for all
                         Options: posts, faqs, brand_voice, custom_docs
            n_results: Number of results to return (default 5)
            min_score: Minimum similarity score 0.0-1.0 (default 0.3)
        """
        config = load_config()
        from scripts.shared.rag import RAGManager

        rag = RAGManager(config["knowledge_base_path"])
        col_list = (
            [c.strip() for c in collections.split(",") if c.strip()]
            if collections
            else None
        )

        try:
            results = rag.search(
                query,
                collections=col_list,
                n_results=n_results,
                min_score=min_score,
            )
            return json.dumps(
                {
                    "query": query,
                    "results_found": len(results),
                    "results": results,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def kb_list_documents(
        collection: str = "custom_docs", limit: int = 50
    ) -> str:
        """
        List documents indexed in the knowledge base.

        Args:
            collection: Collection to list ('posts', 'faqs', 'brand_voice', 'custom_docs')
            limit: Max documents to return
        """
        config = load_config()
        from scripts.shared.rag import RAGManager

        rag = RAGManager(config["knowledge_base_path"])

        try:
            docs = rag.list_documents(collection=collection, limit=limit)
            stats = rag.get_stats()
            return json.dumps(
                {
                    "collection": collection,
                    "document_count": len(docs),
                    "documents": docs,
                    "all_collections_stats": stats,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def kb_delete_document(doc_id: str, collection: str = "custom_docs") -> str:
        """
        Remove a document from the knowledge base.

        Args:
            doc_id: Document ID to delete (from kb_list_documents)
            collection: Collection the document is in
        """
        config = load_config()
        from scripts.shared.rag import RAGManager

        rag = RAGManager(config["knowledge_base_path"])

        try:
            success = rag.delete_document(doc_id, collection=collection)
            return json.dumps(
                {"success": success, "doc_id": doc_id, "collection": collection},
                indent=2,
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, indent=2)
