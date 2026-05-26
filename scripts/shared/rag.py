"""Local RAG (Retrieval-Augmented Generation) knowledge base.

Uses ChromaDB for vector storage and sentence-transformers for local embeddings.
No external API keys required — everything runs on your machine.

Collections:
  - posts: Indexed campaign posts
  - faqs: Frequently asked questions and answers
  - brand_voice: Brand voice guidelines and examples
  - custom_docs: Any other documents added by the user
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_COLLECTION = "custom_docs"
VALID_COLLECTIONS = {"posts", "faqs", "brand_voice", "custom_docs"}
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, 384-dim, works offline


class RAGManager:
    """Manages the local ChromaDB knowledge base with sentence-transformer embeddings."""

    def __init__(self, storage_path: str):
        self.storage_path = Path(storage_path).expanduser()
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._embedding_fn = None

    def _get_client(self):
        """Lazily initialize ChromaDB client."""
        if self._client is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self.storage_path))
        return self._client

    def _get_embedding_fn(self):
        """Lazily initialize sentence-transformers embedding function."""
        if self._embedding_fn is None:
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
            self._embedding_fn = SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL
            )
        return self._embedding_fn

    def _get_collection(self, name: str):
        """Get or create a ChromaDB collection."""
        client = self._get_client()
        return client.get_or_create_collection(
            name=name,
            embedding_function=self._get_embedding_fn(),
            metadata={"hnsw:space": "cosine"},
        )

    def _make_doc_id(self, text: str, source: str = "") -> str:
        """Generate a stable document ID from content hash."""
        content = f"{source}:{text[:200]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def add_document(
        self,
        text: str,
        collection: str = DEFAULT_COLLECTION,
        metadata: dict | None = None,
        doc_id: str | None = None,
    ) -> str:
        """Add a document to the knowledge base.

        Args:
            text: Document text content
            collection: Which collection to add to
            metadata: Optional metadata dict (title, source, tags, etc.)
            doc_id: Optional custom ID; auto-generated if not provided

        Returns:
            Document ID
        """
        if collection not in VALID_COLLECTIONS:
            raise ValueError(f"Invalid collection '{collection}'. Must be one of: {VALID_COLLECTIONS}")

        col = self._get_collection(collection)
        doc_id = doc_id or self._make_doc_id(text, metadata.get("source", "") if metadata else "")

        meta = {
            "added_at": datetime.utcnow().isoformat(),
            "collection": collection,
            **(metadata or {}),
        }

        col.upsert(
            documents=[text],
            metadatas=[meta],
            ids=[doc_id],
        )
        return doc_id

    def add_documents_batch(
        self,
        docs: list[dict],
        collection: str = DEFAULT_COLLECTION,
    ) -> list[str]:
        """Add multiple documents in batch.

        Args:
            docs: List of dicts with 'text', optional 'id', optional 'metadata'
            collection: Target collection

        Returns:
            List of document IDs
        """
        if not docs:
            return []

        if collection not in VALID_COLLECTIONS:
            raise ValueError(f"Invalid collection '{collection}'.")

        col = self._get_collection(collection)
        now = datetime.utcnow().isoformat()

        texts = []
        metadatas = []
        ids = []

        for doc in docs:
            text = doc["text"]
            meta = {"added_at": now, "collection": collection, **(doc.get("metadata") or {})}
            doc_id = doc.get("id") or self._make_doc_id(text, meta.get("source", ""))

            texts.append(text)
            metadatas.append(meta)
            ids.append(doc_id)

        col.upsert(documents=texts, metadatas=metadatas, ids=ids)
        return ids

    def search(
        self,
        query: str,
        collections: list[str] | None = None,
        n_results: int = 5,
        min_score: float = 0.3,
    ) -> list[dict]:
        """Semantic search across one or more collections.

        Args:
            query: Search query text
            collections: Which collections to search (None = all)
            n_results: Max results per collection
            min_score: Minimum similarity score (0.0-1.0, cosine)

        Returns:
            List of result dicts sorted by relevance
        """
        target_collections = collections or list(VALID_COLLECTIONS)
        all_results = []

        for col_name in target_collections:
            try:
                col = self._get_collection(col_name)
                count = col.count()
                if count == 0:
                    continue

                results = col.query(
                    query_texts=[query],
                    n_results=min(n_results, count),
                    include=["documents", "metadatas", "distances"],
                )

                docs = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0]

                for doc, meta, dist in zip(docs, metas, distances):
                    # ChromaDB cosine distance: 0=identical, 2=opposite
                    # Convert to similarity score 0-1
                    score = 1 - (dist / 2)
                    if score >= min_score:
                        all_results.append({
                            "text": doc,
                            "metadata": meta,
                            "score": round(score, 4),
                            "collection": col_name,
                        })
            except Exception:
                continue

        # Sort by relevance score descending
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:n_results]

    def list_documents(
        self, collection: str = DEFAULT_COLLECTION, limit: int = 100
    ) -> list[dict]:
        """List documents in a collection."""
        if collection not in VALID_COLLECTIONS:
            raise ValueError(f"Invalid collection '{collection}'.")

        col = self._get_collection(collection)
        if col.count() == 0:
            return []

        results = col.get(
            limit=limit,
            include=["documents", "metadatas"],
        )

        docs = []
        for doc_id, text, meta in zip(
            results["ids"],
            results.get("documents", []),
            results.get("metadatas", []),
        ):
            docs.append({
                "id": doc_id,
                "text_preview": text[:200] + "..." if len(text) > 200 else text,
                "metadata": meta,
            })
        return docs

    def delete_document(self, doc_id: str, collection: str = DEFAULT_COLLECTION) -> bool:
        """Delete a document by ID."""
        if collection not in VALID_COLLECTIONS:
            raise ValueError(f"Invalid collection '{collection}'.")

        col = self._get_collection(collection)
        try:
            col.delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def get_stats(self) -> dict:
        """Get knowledge base statistics."""
        stats = {}
        for col_name in VALID_COLLECTIONS:
            try:
                col = self._get_collection(col_name)
                stats[col_name] = col.count()
            except Exception:
                stats[col_name] = 0
        stats["total"] = sum(stats.values())
        stats["storage_path"] = str(self.storage_path)
        return stats
