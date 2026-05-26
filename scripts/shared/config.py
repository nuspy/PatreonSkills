"""Load Patreon API credentials and optional configuration.

Priority order for Patreon token:
1. Environment variable PATREON_ACCESS_TOKEN
2. Credential file ~/.patreon/credentials.json (set by auth.py login)
3. Error — prompts user to set env var or run auth.py
"""

import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CRED_FILE = Path.home() / ".patreon" / "credentials.json"


def _load_from_file() -> dict | None:
    """Read credentials from local file, or return None."""
    if not CRED_FILE.exists():
        return None
    try:
        data = json.loads(CRED_FILE.read_text())
        access_token = data.get("access_token", "").strip()
        if access_token:
            return {"access_token": access_token}
    except (json.JSONDecodeError, OSError):
        pass
    return None


def load_config() -> dict:
    """Return configuration dict with Patreon credentials and optional settings."""
    # Priority 1: environment variable
    access_token = os.environ.get("PATREON_ACCESS_TOKEN", "").strip()

    if access_token:
        config: dict = {"access_token": access_token}
    else:
        # Priority 2: credential file set by auth.py login
        creds = _load_from_file()
        if creds:
            config = creds
        else:
            print(
                "Error: Patreon credentials not found.\n\n"
                "Option 1 — Set environment variable:\n"
                '  export PATREON_ACCESS_TOKEN="<your-creator-access-token>"\n\n'
                "Option 2 — Run the auth flow:\n"
                "  python scripts/auth.py login\n\n"
                "Get your Creator Access Token from:\n"
                "  https://www.patreon.com/portal/registration/register-clients\n",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── Optional LLM configuration (model-agnostic, for batch preprocessing) ──
    llm_base_url = os.environ.get("LLM_BASE_URL", "").strip()
    if llm_base_url:
        config["llm_base_url"] = llm_base_url
        config["llm_model"] = os.environ.get("LLM_MODEL", "gpt-3.5-turbo").strip()
        config["llm_api_key"] = os.environ.get("LLM_API_KEY", "").strip()

    # ── Optional search API keys ──
    google_key = os.environ.get("GOOGLE_SEARCH_API_KEY", "").strip()
    if google_key:
        config["google_search_api_key"] = google_key
        config["google_search_cx"] = os.environ.get("GOOGLE_SEARCH_CX", "").strip()

    bing_key = os.environ.get("BING_SEARCH_API_KEY", "").strip()
    if bing_key:
        config["bing_search_api_key"] = bing_key

    # ── Optional browser automation credentials ──
    patreon_email = os.environ.get("PATREON_EMAIL", "").strip()
    if patreon_email:
        config["patreon_email"] = patreon_email
        config["patreon_password"] = os.environ.get("PATREON_PASSWORD", "").strip()

    # ── Storage paths ──
    config["knowledge_base_path"] = os.environ.get(
        "KNOWLEDGE_BASE_PATH", str(Path.home() / ".patreon" / "knowledge_base")
    )
    config["browser_session_path"] = os.environ.get(
        "BROWSER_SESSION_PATH", str(Path.home() / ".patreon" / "browser_session")
    )
    config["browser_headless"] = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"

    return config
