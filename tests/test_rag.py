"""Tests for scripts/shared/rag.py.

Uses an in-memory ChromaDB (EphemeralClient) and a dummy embedding function
to avoid downloading any ML models.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def rag(tmp_path, monkeypatch, dummy_embedding):
    """RAGManager backed by ephemeral ChromaDB + dummy embeddings."""
    import chromadb
    from chromadb.utils import embedding_functions as ef

    # Replace PersistentClient with an in-memory client (no disk writes)
    ephemeral = chromadb.EphemeralClient()
    monkeypatch.setattr(chromadb, "PersistentClient", lambda path: ephemeral)

    # Replace SentenceTransformer with the dummy (no model download)
    monkeypatch.setattr(
        ef,
        "SentenceTransformerEmbeddingFunction",
        lambda model_name: dummy_embedding,
    )

    from scripts.shared.rag import RAGManager

    return RAGManager(str(tmp_path))


class TestAddAndList:
    def test_add_document_returns_id(self, rag):
        doc_id = rag.add_document(
            "Patreon creator guide for beginners.",
            collection="custom_docs",
            metadata={"title": "Guide"},
        )
        assert isinstance(doc_id, str)
        assert len(doc_id) == 16  # sha256 hex [:16]

    def test_add_document_and_list(self, rag):
        rag.add_document("First document", collection="faqs")
        rag.add_document("Second document", collection="faqs")

        docs = rag.list_documents("faqs")
        assert len(docs) == 2
        assert all("id" in d for d in docs)
        assert all("text_preview" in d for d in docs)

    def test_invalid_collection_raises_value_error(self, rag):
        with pytest.raises(ValueError, match="Invalid collection"):
            rag.add_document("text", collection="not_a_real_collection")

    def test_custom_doc_id_respected(self, rag):
        rag.add_document("Content", collection="brand_voice", doc_id="my_custom_id")
        docs = rag.list_documents("brand_voice")
        assert docs[0]["id"] == "my_custom_id"

    def test_batch_add(self, rag):
        batch = [
            {"text": "Item one", "metadata": {"src": "batch"}},
            {"text": "Item two", "metadata": {"src": "batch"}},
            {"text": "Item three", "id": "fixed_id_111"},
        ]
        ids = rag.add_documents_batch(batch, collection="posts")
        assert len(ids) == 3
        assert "fixed_id_111" in ids
        assert len(rag.list_documents("posts")) == 3

    def test_batch_add_empty_list_returns_empty(self, rag):
        ids = rag.add_documents_batch([], collection="custom_docs")
        assert ids == []


class TestSearch:
    def test_search_returns_results(self, rag):
        rag.add_document("How to grow your Patreon audience.", collection="custom_docs")
        rag.add_document("Monthly revenue tracking spreadsheet.", collection="custom_docs")

        results = rag.search("grow audience", collections=["custom_docs"], n_results=2)
        assert len(results) > 0
        assert "text" in results[0]
        assert "score" in results[0]
        assert "collection" in results[0]
        assert results[0]["score"] >= 0.0

    def test_search_empty_collection_returns_empty(self, rag):
        results = rag.search("anything", collections=["faqs"], n_results=5)
        assert results == []

    def test_search_respects_n_results(self, rag):
        for i in range(5):
            rag.add_document(f"Document number {i} about creators.", collection="posts")

        results = rag.search("creator document", collections=["posts"], n_results=3)
        assert len(results) <= 3

    def test_search_across_multiple_collections(self, rag):
        rag.add_document("Post about content strategy.", collection="posts")
        rag.add_document("FAQ: how do I start?", collection="faqs")

        results = rag.search("strategy", collections=["posts", "faqs"], n_results=5)
        collections_found = {r["collection"] for r in results}
        assert len(results) >= 1
        assert len(collections_found) >= 1


class TestDelete:
    def test_delete_existing_document(self, rag):
        doc_id = rag.add_document("To be deleted", collection="custom_docs")
        assert len(rag.list_documents("custom_docs")) == 1

        deleted = rag.delete_document(doc_id, collection="custom_docs")
        assert deleted is True
        assert len(rag.list_documents("custom_docs")) == 0

    def test_delete_nonexistent_returns_false(self, rag):
        # ChromaDB raises when deleting non-existent IDs; RAGManager catches it
        result = rag.delete_document("nonexistent_id_xyz", collection="custom_docs")
        assert result is False


class TestStats:
    def test_get_stats_counts_per_collection(self, rag):
        rag.add_document("Post A", collection="posts")
        rag.add_document("Post B", collection="posts")
        rag.add_document("FAQ entry", collection="faqs")

        stats = rag.get_stats()
        assert stats["posts"] == 2
        assert stats["faqs"] == 1
        assert stats["brand_voice"] == 0
        assert stats["custom_docs"] == 0
        assert stats["total"] == 3
        assert "storage_path" in stats

    def test_get_stats_empty_kb(self, rag):
        stats = rag.get_stats()
        assert stats["total"] == 0
