"""Unit tests for scripts/shared/config.py.

All tests use the 'fake_token' autouse fixture from conftest.py.
Tests that check failure paths explicitly delete the env var and
redirect CRED_FILE via the 'cred_file' fixture.
"""

from __future__ import annotations

import json

import pytest


class TestLoadConfigTokenPriority:
    def test_reads_env_token(self):
        from scripts.shared.config import load_config

        cfg = load_config()
        assert cfg["access_token"] == "pat_test_fake_ci_token_0000000"

    def test_env_overrides_cred_file(self, cred_file, monkeypatch):
        monkeypatch.setenv("PATREON_ACCESS_TOKEN", "pat_env")
        cred_file.write_text(json.dumps({"access_token": "pat_file"}))

        from scripts.shared.config import load_config

        cfg = load_config()
        assert cfg["access_token"] == "pat_env"

    def test_falls_back_to_cred_file(self, cred_file, monkeypatch):
        monkeypatch.delenv("PATREON_ACCESS_TOKEN", raising=False)
        cred_file.write_text(json.dumps({"access_token": "pat_from_file"}))

        from scripts.shared.config import load_config

        cfg = load_config()
        assert cfg["access_token"] == "pat_from_file"

    def test_no_credentials_calls_sys_exit(self, cred_file, monkeypatch):
        monkeypatch.delenv("PATREON_ACCESS_TOKEN", raising=False)
        # cred_file not written — file does not exist

        from scripts.shared.config import load_config

        with pytest.raises(SystemExit):
            load_config()

    def test_corrupt_cred_file_falls_through_to_exit(self, cred_file, monkeypatch):
        monkeypatch.delenv("PATREON_ACCESS_TOKEN", raising=False)
        cred_file.write_text("{{{{ not valid json")

        from scripts.shared.config import load_config

        with pytest.raises(SystemExit):
            load_config()

    def test_empty_token_in_cred_file_falls_through_to_exit(self, cred_file, monkeypatch):
        monkeypatch.delenv("PATREON_ACCESS_TOKEN", raising=False)
        cred_file.write_text(json.dumps({"access_token": ""}))

        from scripts.shared.config import load_config

        with pytest.raises(SystemExit):
            load_config()


class TestLoadConfigOptionalSettings:
    def test_llm_config_included_when_env_set(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setenv("LLM_MODEL", "hermes3")
        monkeypatch.setenv("LLM_API_KEY", "")

        from scripts.shared.config import load_config

        cfg = load_config()
        assert cfg["llm_base_url"] == "http://localhost:11434"
        assert cfg["llm_model"] == "hermes3"
        assert "llm_api_key" in cfg

    def test_llm_config_absent_when_not_set(self, monkeypatch):
        monkeypatch.delenv("LLM_BASE_URL", raising=False)

        from scripts.shared.config import load_config

        cfg = load_config()
        assert "llm_base_url" not in cfg

    def test_google_search_keys_included(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "gkey_test")
        monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx_test")

        from scripts.shared.config import load_config

        cfg = load_config()
        assert cfg["google_search_api_key"] == "gkey_test"
        assert cfg["google_search_cx"] == "cx_test"

    def test_storage_paths_default_under_home(self, monkeypatch):
        monkeypatch.delenv("KNOWLEDGE_BASE_PATH", raising=False)
        monkeypatch.delenv("BROWSER_SESSION_PATH", raising=False)

        from scripts.shared.config import load_config

        cfg = load_config()
        assert "knowledge_base" in cfg["knowledge_base_path"]
        assert "browser_session" in cfg["browser_session_path"]

    def test_custom_storage_paths_respected(self, monkeypatch, tmp_path):
        kb_path = str(tmp_path / "kb")
        bs_path = str(tmp_path / "browser")
        monkeypatch.setenv("KNOWLEDGE_BASE_PATH", kb_path)
        monkeypatch.setenv("BROWSER_SESSION_PATH", bs_path)

        from scripts.shared.config import load_config

        cfg = load_config()
        assert cfg["knowledge_base_path"] == kb_path
        assert cfg["browser_session_path"] == bs_path

    def test_browser_headless_defaults_true(self, monkeypatch):
        monkeypatch.delenv("BROWSER_HEADLESS", raising=False)

        from scripts.shared.config import load_config

        cfg = load_config()
        assert cfg["browser_headless"] is True

    def test_browser_headless_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("BROWSER_HEADLESS", "false")

        from scripts.shared.config import load_config

        cfg = load_config()
        assert cfg["browser_headless"] is False
