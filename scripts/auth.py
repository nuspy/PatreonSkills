"""Patreon OAuth2 authentication CLI.

Helps creators authenticate and store credentials locally.
For most use cases, simply set PATREON_ACCESS_TOKEN as an environment variable
using your Creator Access Token from:
  https://www.patreon.com/portal/registration/register-clients

For OAuth2 flow (multi-user or apps that can't use env vars):
  python scripts/auth.py login    - Open OAuth authorization URL
  python scripts/auth.py status   - Check current auth status
  python scripts/auth.py logout   - Remove stored credentials
  python scripts/auth.py token TOKEN - Manually store a creator access token
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CRED_FILE = Path.home() / ".patreon" / "credentials.json"
PATREON_OAUTH_AUTH_URL = "https://www.patreon.com/oauth2/authorize"


def cmd_status() -> None:
    """Show current authentication status."""
    import os

    env_token = os.environ.get("PATREON_ACCESS_TOKEN", "")
    if env_token:
        print(f"✅ Authenticated via PATREON_ACCESS_TOKEN environment variable")
        print(f"   Token: {env_token[:8]}...{env_token[-4:]}")
        return

    if CRED_FILE.exists():
        try:
            data = json.loads(CRED_FILE.read_text())
            token = data.get("access_token", "")
            if token:
                print(f"✅ Authenticated via credential file: {CRED_FILE}")
                print(f"   Token: {token[:8]}...{token[-4:]}")
                name = data.get("name", "")
                if name:
                    print(f"   Creator: {name}")
                return
        except Exception:
            pass

    print("❌ Not authenticated.")
    print("\nOptions:")
    print("  1. Set PATREON_ACCESS_TOKEN environment variable")
    print("  2. Run: python scripts/auth.py token YOUR_TOKEN")
    print("  3. Run: python scripts/auth.py login (OAuth2 flow)")
    print("\nGet your token: https://www.patreon.com/portal/registration/register-clients")


def cmd_token(token: str) -> None:
    """Store a creator access token in the credentials file."""
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"access_token": token}

    # Try to verify the token
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://www.patreon.com/api/oauth2/v2/identity?fields[user]=full_name,email",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            identity = json.loads(resp.read())
        attrs = identity.get("data", {}).get("attributes", {})
        data["name"] = attrs.get("full_name", "")
        data["email"] = attrs.get("email", "")
        print(f"✅ Token verified for: {data['name']} ({data['email']})")
    except Exception as e:
        print(f"⚠️  Could not verify token: {e}")
        print("   Token saved anyway — it may still be valid.")

    CRED_FILE.write_text(json.dumps(data, indent=2))
    print(f"💾 Credentials saved to: {CRED_FILE}")


def cmd_login(client_id: str = "", redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob") -> None:
    """Start the OAuth2 authorization flow."""
    if not client_id:
        print("OAuth2 login requires a Patreon client ID.")
        print("Get one at: https://www.patreon.com/portal/registration/register-clients")
        print("\nAlternatively, use 'python scripts/auth.py token YOUR_CREATOR_TOKEN'")
        print("to store a Creator Access Token directly (simpler for single-creator use).")
        return

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "identity identity[email] campaigns campaigns.members",
    }
    from urllib.parse import urlencode
    auth_url = f"{PATREON_OAUTH_AUTH_URL}?{urlencode(params)}"

    print("Open this URL in your browser to authorize:")
    print(f"\n  {auth_url}\n")
    print("After authorization, run:")
    print("  python scripts/auth.py token YOUR_ACCESS_TOKEN")


def cmd_logout() -> None:
    """Remove stored credentials."""
    if CRED_FILE.exists():
        CRED_FILE.unlink()
        print(f"✅ Credentials removed: {CRED_FILE}")
    else:
        print("No stored credentials found.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patreon Creator Skill — Authentication",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/auth.py status
  python scripts/auth.py token pat_abc123...
  python scripts/auth.py logout

Get your Creator Access Token:
  https://www.patreon.com/portal/registration/register-clients
""",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show authentication status")
    subparsers.add_parser("logout", help="Remove stored credentials")

    token_parser = subparsers.add_parser("token", help="Store a creator access token")
    token_parser.add_argument("value", help="Your Patreon Creator Access Token")

    login_parser = subparsers.add_parser("login", help="Start OAuth2 flow")
    login_parser.add_argument(
        "--client-id", default="", help="Patreon OAuth2 client ID"
    )

    args = parser.parse_args()

    if args.command == "status" or args.command is None:
        cmd_status()
    elif args.command == "token":
        cmd_token(args.value)
    elif args.command == "login":
        cmd_login(client_id=args.client_id)
    elif args.command == "logout":
        cmd_logout()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
