"""Smoke tests: verify key modules are importable and expose expected API surface."""

from __future__ import annotations

import importlib

import pytest


class TestSharedModuleAPIs:
    def test_config_module(self):
        mod = importlib.import_module("scripts.shared.config")
        assert callable(mod.load_config)
        assert hasattr(mod, "CRED_FILE")

    def test_patreon_client_module(self):
        mod = importlib.import_module("scripts.shared.patreon_client")
        assert hasattr(mod, "PatreonClient")
        assert hasattr(mod, "PatreonError")
        assert hasattr(mod, "PATREON_API_BASE")
        assert hasattr(mod, "WEBHOOK_EVENTS")

    def test_rag_module(self):
        mod = importlib.import_module("scripts.shared.rag")
        assert hasattr(mod, "RAGManager")
        assert hasattr(mod, "VALID_COLLECTIONS")
        assert hasattr(mod, "EMBEDDING_MODEL")
        assert isinstance(mod.VALID_COLLECTIONS, set)

    def test_patreon_client_methods(self):
        from scripts.shared.patreon_client import PatreonClient

        expected = [
            "get_identity",
            "get_campaigns",
            "get_campaign",
            "get_members",
            "get_all_members",
            "get_posts",
            "get_all_posts",
            "get_post",
            "create_webhook",
            "update_webhook",
            "delete_webhook",
        ]
        for method in expected:
            assert hasattr(PatreonClient, method), f"PatreonClient missing: {method}"

    def test_rag_manager_methods(self):
        from scripts.shared.rag import RAGManager

        expected = [
            "add_document",
            "add_documents_batch",
            "search",
            "list_documents",
            "delete_document",
            "get_stats",
        ]
        for method in expected:
            assert hasattr(RAGManager, method), f"RAGManager missing: {method}"


class TestToolModuleAPIs:
    @pytest.mark.parametrize(
        "module_name",
        [
            "scripts.tools.campaign_tools",
            "scripts.tools.member_tools",
            "scripts.tools.content_tools",
            "scripts.tools.competitor_tools",
            "scripts.tools.automation_tools",
            "scripts.tools.webhook_tools",
            "scripts.tools.rag_tools",
            "scripts.tools.reporting_tools",
        ],
    )
    def test_tool_module_has_register(self, module_name):
        """Every tool module must expose a register(mcp) callable."""
        pytest.importorskip("mcp", reason="mcp package not installed in this environment")
        mod = importlib.import_module(module_name)
        assert hasattr(mod, "register"), f"{module_name} is missing register()"
        assert callable(mod.register), f"{module_name}.register is not callable"
