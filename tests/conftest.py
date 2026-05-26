"""Shared pytest fixtures for patreon-creator-skill tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def fake_token(monkeypatch):
    """Set a fake Patreon token for every test so load_config() never exits."""
    monkeypatch.setenv("PATREON_ACCESS_TOKEN", "pat_test_fake_ci_token_0000000")


@pytest.fixture
def cred_file(tmp_path, monkeypatch):
    """Create a temp credentials.json and redirect CRED_FILE to it."""
    import scripts.shared.config as cfg_mod

    path = tmp_path / "credentials.json"
    monkeypatch.setattr(cfg_mod, "CRED_FILE", path)
    return path


@pytest.fixture
def dummy_embedding():
    """Fast embedding function returning 384-dim constant vectors.
    Use this to patch SentenceTransformerEmbeddingFunction in RAG tests
    so no model is downloaded.
    """

    class _DummyEmbedding:
        def __call__(self, input):  # noqa: A002
            return [[0.1] * 384 for _ in input]

    return _DummyEmbedding()
