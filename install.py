#!/usr/bin/env python3
"""
Patreon Creator Skill — Autonomous Installer
=============================================
Works fully non-interactively. All configuration via CLI args.
No dependencies beyond Python 3.11+ stdlib.

Usage examples:
    python install.py --token pat_xxx --client claude
    python install.py --token pat_xxx --client cursor --dir ~/myskills/patreon
    python install.py --token pat_xxx --client claude,cursor --playwright
    python install.py --token pat_xxx --no-mcp --no-verify
    python install.py --token pat_xxx --llm-url http://localhost:11434 --llm-model hermes3
    python install.py --local-path ~/patreonskills --token pat_xxx --client vscode

    # One-liner (download + run):
    curl -sSL https://raw.githubusercontent.com/nuspy/patreonskills/main/install.py | python - --token pat_xxx --client claude
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

VERSION = "1.0.0"
REPO_URL = "https://github.com/nuspy/patreonskills"
SERVER_NAME = "patreon-creator-skill"
CRED_DIR = Path.home() / ".patreon"
CRED_FILE = CRED_DIR / "credentials.json"
MIN_PYTHON = (3, 11)

# MCP config file paths per client per platform
_sys = platform.system()
_appdata = Path(os.environ.get("APPDATA", "~")).expanduser()

MCP_CONFIG_PATHS: dict[str, Path] = {
    "claude": {
        "Darwin":  Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        "Windows": _appdata / "Claude" / "claude_desktop_config.json",
        "Linux":   Path.home() / ".config" / "Claude" / "claude_desktop_config.json",
    }.get(_sys, Path.home() / ".config" / "Claude" / "claude_desktop_config.json"),

    "cursor": {
        "Darwin":  Path.home() / ".cursor" / "mcp.json",
        "Windows": _appdata / "Cursor" / "mcp.json",
        "Linux":   Path.home() / ".cursor" / "mcp.json",
    }.get(_sys, Path.home() / ".cursor" / "mcp.json"),

    "vscode": {
        "Darwin":  Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json",
        "Windows": _appdata / "Code" / "User" / "settings.json",
        "Linux":   Path.home() / ".config" / "Code" / "User" / "settings.json",
    }.get(_sys, Path.home() / ".config" / "Code" / "User" / "settings.json"),
}

# ANSI color codes (disabled on Windows or if NO_COLOR is set)
_use_color = _sys != "Windows" and not os.environ.get("NO_COLOR") and sys.stdout.isatty()

COLORS = {
    "reset":  "\033[0m"   if _use_color else "",
    "bold":   "\033[1m"   if _use_color else "",
    "red":    "\033[91m"  if _use_color else "",
    "green":  "\033[92m"  if _use_color else "",
    "yellow": "\033[93m"  if _use_color else "",
    "blue":   "\033[94m"  if _use_color else "",
    "cyan":   "\033[96m"  if _use_color else "",
    "dim":    "\033[2m"   if _use_color else "",
}

# Global quiet flag (set after arg parsing)
_quiet = False


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "info") -> None:
    """Print colored status messages. Always prints if level == 'error'."""
    if _quiet and level not in ("error", "summary", "bold"):
        return
    c = COLORS
    prefixes = {
        "info":    f"{c['blue']}ℹ{c['reset']}  ",
        "ok":      f"{c['green']}✓{c['reset']}  ",
        "warn":    f"{c['yellow']}⚠{c['reset']}  ",
        "error":   f"{c['red']}✗{c['reset']}  ",
        "step":    f"{c['cyan']}→{c['reset']}  ",
        "bold":    f"{c['bold']}",
        "summary": "",
    }
    prefix = prefixes.get(level, "   ")
    suffix = c['reset'] if level == "bold" else ""
    stream = sys.stderr if level == "error" else sys.stdout
    print(f"{prefix}{msg}{suffix}", file=stream)


def log_section(title: str) -> None:
    """Print a section divider."""
    if _quiet:
        return
    c = COLORS
    print(f"\n{c['bold']}{c['cyan']}── {title} ──{c['reset']}", file=sys.stdout)


# ── Argument Parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Patreon Creator Skill — Autonomous Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Token (at least one required)
    tok = p.add_mutually_exclusive_group()
    tok.add_argument("--token", metavar="PAT_TOKEN",
                     help="Patreon Creator Access Token (pat_xxx...)")
    tok.add_argument("--token-file", metavar="FILE",
                     help="Path to a file containing the token (for CI/CD)")

    # Source
    src = p.add_mutually_exclusive_group()
    src.add_argument("--repo", metavar="URL", default=REPO_URL,
                     help=f"Git repository URL to clone (default: {REPO_URL})")
    src.add_argument("--local-path", metavar="PATH",
                     help="Use an already-cloned local directory (skip clone)")

    # Installation
    p.add_argument("--dir", metavar="DIR", default="~/patreon-skill",
                   help="Installation directory (default: ~/patreon-skill)")
    p.add_argument("--branch", metavar="BRANCH", default=None,
                   help="Git branch to checkout after cloning")
    p.add_argument("--venv", action="store_true",
                   help="Create a Python virtual environment at DIR/.venv")
    p.add_argument("--no-pip", action="store_true",
                   help="Skip pip install (assume deps already installed)")
    p.add_argument("--playwright", action="store_true",
                   help="Install Playwright Chromium browser after pip install")
    p.add_argument("--no-playwright", action="store_true",
                   help="Explicitly skip Playwright install (default: skip)")

    # MCP client configuration
    p.add_argument("--client", "--mcp-client", metavar="CLIENTS",
                   dest="client", default=None,
                   help="Comma-separated MCP clients to configure: claude,cursor,vscode (default: auto-detect)")
    p.add_argument("--mcp-config-path", metavar="PATH",
                   help="Explicit MCP config JSON path (for custom clients)")
    p.add_argument("--no-mcp", action="store_true",
                   help="Skip all MCP client configuration")

    # Optional credentials / config
    p.add_argument("--email", "--patreon-email", metavar="EMAIL",
                   dest="patreon_email",
                   help="Patreon email for browser automation")
    p.add_argument("--password", "--patreon-password", metavar="PASS",
                   dest="patreon_password",
                   help="Patreon password for browser automation")
    p.add_argument("--llm-url", "--llm-base-url", metavar="URL",
                   dest="llm_base_url",
                   help="Optional LLM endpoint (e.g. http://localhost:11434)")
    p.add_argument("--llm-model", metavar="MODEL", default=None,
                   help="LLM model name (default: hermes3)")
    p.add_argument("--llm-api-key", metavar="KEY", default=None,
                   help="LLM API key (empty for local Ollama)")
    p.add_argument("--google-key", "--google-search-key", metavar="KEY",
                   dest="google_search_key",
                   help="Google Custom Search API key")
    p.add_argument("--google-cx", "--google-search-cx", metavar="CX",
                   dest="google_search_cx",
                   help="Google Custom Search Engine ID")
    p.add_argument("--bing-key", "--bing-search-key", metavar="KEY",
                   dest="bing_search_key",
                   help="Bing Web Search API key")

    # Behavior
    p.add_argument("--no-verify", "--skip-test", action="store_true",
                   dest="no_verify",
                   help="Skip final connection test")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress progress output (only errors + final summary)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be done without executing")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing MCP config entries")
    p.add_argument("--output-json", metavar="FILE",
                   help="Write structured result JSON to this file")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    return p.parse_args()


# ── Step Functions ─────────────────────────────────────────────────────────────

def check_python_version() -> dict:
    """Assert Python >= 3.11. Exits with a helpful message if check fails."""
    ver = sys.version_info
    ver_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    if ver < MIN_PYTHON:
        log(f"Python {'.'.join(map(str, MIN_PYTHON))}+ required, found {ver_str}", "error")
        log("Download Python from https://python.org/downloads", "info")
        sys.exit(1)
    log(f"Python {ver_str} — OK", "ok")
    return {"version": ver_str, "ok": True}


def resolve_python_executable() -> str:
    """Return the Python executable path to use in MCP config."""
    if sys.prefix != sys.base_prefix:
        return sys.executable
    py = shutil.which("python3") or shutil.which("python") or sys.executable
    return py


def clone_or_update(repo_url: str, install_dir: Path, branch: Optional[str],
                    dry_run: bool) -> dict:
    """Clone repo to install_dir, or git pull if already cloned."""
    if install_dir.exists():
        git_dir = install_dir / ".git"
        if not git_dir.exists():
            log(f"{install_dir} exists but is not a git repo. Use --local-path or choose a different --dir.", "error")
            sys.exit(1)
        log(f"Repository already exists at {install_dir}, pulling latest…", "step")
        if not dry_run:
            cmd = ["git", "-C", str(install_dir), "pull", "--ff-only"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log(f"git pull failed: {result.stderr.strip()}", "warn")
        log(f"Repository updated", "ok")
        action = "updated"
    else:
        log(f"Cloning {repo_url} → {install_dir}…", "step")
        cmd = ["git", "clone", repo_url, str(install_dir)]
        if dry_run:
            log(f"DRY-RUN: would run: {' '.join(cmd)}", "info")
        else:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log(f"git clone failed:\n{result.stderr.strip()}", "error")
                log("Make sure git is installed and the URL is accessible.", "info")
                sys.exit(1)
        log(f"Repository cloned to {install_dir}", "ok")
        action = "cloned"

    if branch and not dry_run and install_dir.exists():
        cmd = ["git", "-C", str(install_dir), "checkout", branch]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log(f"Could not checkout branch '{branch}': {result.stderr.strip()}", "warn")

    return {"action": action, "repo": repo_url, "install_dir": str(install_dir)}


def use_local_path(local_path: str) -> tuple[Path, dict]:
    """Validate and use a local directory instead of cloning."""
    p = Path(local_path).expanduser().resolve()
    if not p.exists():
        log(f"Local path does not exist: {p}", "error")
        sys.exit(1)
    if not (p / "scripts").exists():
        log(f"Directory {p} doesn't look like a patreonskills repo (no scripts/ folder)", "warn")
    log(f"Using local path: {p}", "ok")
    return p, {"action": "local", "path": str(p)}


def create_venv(install_dir: Path, dry_run: bool) -> Path:
    """Create a venv at install_dir/.venv. Returns the venv Python path."""
    venv_dir = install_dir / ".venv"
    if venv_dir.exists():
        log(f"Virtual environment already exists at {venv_dir}", "ok")
    else:
        log(f"Creating virtual environment at {venv_dir}…", "step")
        cmd = [sys.executable, "-m", "venv", str(venv_dir)]
        if dry_run:
            log(f"DRY-RUN: would run: {' '.join(cmd)}", "info")
        else:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log(f"venv creation failed: {result.stderr.strip()}", "error")
                sys.exit(1)
        log(f"Virtual environment created", "ok")

    if _sys == "Windows":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python"
    return venv_python


def install_requirements(install_dir: Path, python_exe: str, dry_run: bool) -> dict:
    """Install pip requirements from scripts/requirements.txt."""
    req_file = install_dir / "scripts" / "requirements.txt"
    if not req_file.exists():
        log(f"requirements.txt not found at {req_file}", "error")
        sys.exit(1)

    log("Installing dependencies…", "step")
    cmd = [python_exe, "-m", "pip", "install", "--upgrade", "-r", str(req_file)]

    if dry_run:
        log(f"DRY-RUN: would run: {' '.join(cmd)}", "info")
        return {"ok": True, "dry_run": True}

    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        log("pip install failed. Check the output above.", "error")
        sys.exit(1)
    log("Dependencies installed", "ok")
    return {"ok": True}


def install_playwright(python_exe: str, dry_run: bool) -> dict:
    """Install Playwright Chromium browser."""
    log("Installing Playwright Chromium browser…", "step")
    cmd = [python_exe, "-m", "playwright", "install", "chromium"]

    if dry_run:
        log(f"DRY-RUN: would run: {' '.join(cmd)}", "info")
        return {"ok": True, "dry_run": True}

    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        log("Playwright install failed. Browser automation features will not work.", "warn")
        log("Run manually: playwright install chromium", "info")
        return {"ok": False, "error": "playwright install failed"}
    log("Playwright Chromium installed", "ok")
    return {"ok": True}


def resolve_token(args: argparse.Namespace) -> str:
    """Resolve token from --token, --token-file, or existing credentials file."""
    if args.token:
        return args.token.strip()
    if args.token_file:
        tf = Path(args.token_file).expanduser()
        if not tf.exists():
            log(f"Token file not found: {tf}", "error")
            sys.exit(1)
        return tf.read_text().strip()
    if CRED_FILE.exists():
        try:
            existing = json.loads(CRED_FILE.read_text())
            token = existing.get("access_token", "").strip()
            if token:
                log(f"Using existing token from {CRED_FILE}", "info")
                return token
        except (json.JSONDecodeError, OSError):
            pass
    log("No token provided. Use --token pat_xxx or --token-file /path/to/file", "error")
    log("Get your Creator Access Token at: https://www.patreon.com/portal", "info")
    sys.exit(1)


def store_credentials(token: str, args: argparse.Namespace,
                      install_dir: Path, dry_run: bool) -> dict:
    """Store credentials in ~/.patreon/credentials.json and .env in install_dir."""
    cred_data: dict = {"access_token": token}
    if args.patreon_email:
        cred_data["patreon_email"] = args.patreon_email
    if args.patreon_password:
        cred_data["patreon_password"] = args.patreon_password

    if CRED_FILE.exists() and not args.force:
        try:
            existing = json.loads(CRED_FILE.read_text())
            for k, v in existing.items():
                if k not in cred_data:
                    cred_data[k] = v
        except (json.JSONDecodeError, OSError):
            pass

    if dry_run:
        log(f"DRY-RUN: would write credentials to {CRED_FILE}", "info")
    else:
        CRED_DIR.mkdir(parents=True, exist_ok=True)
        CRED_FILE.write_text(json.dumps(cred_data, indent=2))
        try:
            os.chmod(CRED_FILE, 0o600)
        except OSError:
            pass
        log(f"Credentials saved to {CRED_FILE}", "ok")

    env_vars: dict[str, str] = {"PATREON_ACCESS_TOKEN": token}

    if args.llm_base_url:
        env_vars["LLM_BASE_URL"] = args.llm_base_url
    if args.llm_model:
        env_vars["LLM_MODEL"] = args.llm_model
    if args.llm_api_key is not None:
        env_vars["LLM_API_KEY"] = args.llm_api_key
    if args.google_search_key:
        env_vars["GOOGLE_SEARCH_API_KEY"] = args.google_search_key
    if args.google_search_cx:
        env_vars["GOOGLE_SEARCH_CX"] = args.google_search_cx
    if args.bing_search_key:
        env_vars["BING_SEARCH_API_KEY"] = args.bing_search_key
    if args.patreon_email:
        env_vars["PATREON_EMAIL"] = args.patreon_email
    if args.patreon_password:
        env_vars["PATREON_PASSWORD"] = args.patreon_password

    env_file = install_dir / ".env"

    existing_env: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing_env[k.strip()] = v.strip()

    if not args.force:
        for k in list(env_vars.keys()):
            if k in existing_env and k != "PATREON_ACCESS_TOKEN":
                pass
    merged = {**existing_env, **env_vars}

    if dry_run:
        log(f"DRY-RUN: would write .env to {env_file}", "info")
    else:
        lines = [f"{k}={v}" for k, v in merged.items()]
        env_file.write_text("\n".join(lines) + "\n")
        try:
            os.chmod(env_file, 0o600)
        except OSError:
            pass
        log(f".env written to {env_file}", "ok")

    return {"cred_file": str(CRED_FILE), "env_file": str(env_file)}


def build_mcp_server_entry(install_dir: Path, python_exe: str, token: str) -> dict:
    """Build the MCP server config dict for inclusion in client configs."""
    if _sys == "Windows":
        cwd = str(install_dir).replace("\\", "/")
        command = python_exe.replace("\\", "/")
    else:
        cwd = str(install_dir)
        command = python_exe

    return {
        "command": command,
        "args": ["-m", "scripts.mcp_server"],
        "cwd": cwd,
        "env": {"PATREON_ACCESS_TOKEN": token},
    }


def detect_existing_mcp_clients() -> list[str]:
    """Check which MCP config files exist on disk. Returns detected client names."""
    detected = []
    for client_name, config_path in MCP_CONFIG_PATHS.items():
        if config_path.exists():
            detected.append(client_name)
    return detected


def configure_mcp_client(
    client_name: str,
    config_path: Path,
    server_entry: dict,
    dry_run: bool,
    force: bool,
) -> dict:
    """Write the server entry into the client's MCP config file."""
    result = {"client": client_name, "path": str(config_path)}

    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log(f"Could not read {config_path}: {e}. Creating new config.", "warn")

    if client_name == "vscode":
        existing_entry = config.get("mcp", {}).get("servers", {}).get(SERVER_NAME)
    else:
        existing_entry = config.get("mcpServers", {}).get(SERVER_NAME)

    if existing_entry and not force:
        log(f"{client_name}: '{SERVER_NAME}' already in config (use --force to overwrite)", "warn")
        result["action"] = "skipped"
        return result

    if client_name == "vscode":
        entry = {"type": "stdio", **server_entry}
        config.setdefault("mcp", {}).setdefault("servers", {})[SERVER_NAME] = entry
    else:
        config.setdefault("mcpServers", {})[SERVER_NAME] = server_entry

    if dry_run:
        log(f"DRY-RUN: would write MCP config to {config_path}", "info")
        result["action"] = "dry_run"
        return result

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    log(f"{client_name}: config written to {config_path}", "ok")
    result["action"] = "added"
    return result


def run_connection_test(install_dir: Path, python_exe: str) -> dict:
    """Run a minimal async connection test against the Patreon API."""
    log("Testing Patreon API connection…", "step")

    test_code = (
        "import asyncio, sys; sys.path.insert(0, '.')\n"
        "from scripts.shared.patreon_client import PatreonClient\n"
        "from scripts.shared.config import load_config\n"
        "async def test():\n"
        "    cfg = load_config()\n"
        "    async with PatreonClient(cfg['access_token']) as c:\n"
        "        data = await c.get_identity()\n"
        "    attrs = data.get('data', {}).get('attributes', {})\n"
        "    name = attrs.get('full_name', attrs.get('vanity', '?'))\n"
        "    print(f'OK:{name}')\n"
        "asyncio.run(test())\n"
    )

    try:
        result = subprocess.run(
            [python_exe, "-c", test_code],
            cwd=str(install_dir),
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            if output.startswith("OK:"):
                creator_name = output[3:]
                log(f"Connected as: {creator_name}", "ok")
                return {"success": True, "creator_name": creator_name}
        err = (result.stderr or result.stdout).strip().split("\n")[-1]
        log(f"Connection test failed: {err}", "warn")
        return {"success": False, "error": err}
    except subprocess.TimeoutExpired:
        log("Connection test timed out (20s). Check your PATREON_ACCESS_TOKEN.", "warn")
        return {"success": False, "error": "timeout"}
    except Exception as e:
        log(f"Connection test error: {e}", "warn")
        return {"success": False, "error": str(e)}


def print_summary(results: dict) -> None:
    """Print a formatted installation summary."""
    c = COLORS
    divider = f"{c['dim']}{'─' * 54}{c['reset']}"

    print(f"\n{divider}")
    print(f"{c['bold']}  Patreon Creator Skill — Installation Summary{c['reset']}")
    print(divider)

    install_dir = results.get("install_dir", "?")
    python_exe  = results.get("python_exe", "?")
    token_stored = results.get("token_stored", False)
    test = results.get("connection_test") or {}
    mcp_clients = results.get("mcp_clients", [])

    print(f"  Installed to:   {c['cyan']}{install_dir}{c['reset']}")
    print(f"  Python:         {python_exe}")
    print(f"  Token stored:   {'~/.patreon/credentials.json' if token_stored else c['red']+'not stored'+c['reset']}")

    if test.get("success"):
        print(f"  Connection:     {c['green']}✓ Connected as \"{test['creator_name']}\"{c['reset']}")
    elif test:
        print(f"  Connection:     {c['yellow']}⚠ Test failed — {test.get('error','unknown')}{c['reset']}")
    else:
        print(f"  Connection:     {c['dim']}(skipped){c['reset']}")

    if mcp_clients:
        print(f"\n  MCP Clients Configured:")
        for mc in mcp_clients:
            icon = f"{c['green']}✓{c['reset']}" if mc.get("action") == "added" else \
                   f"{c['yellow']}–{c['reset']}" if mc.get("action") == "skipped" else \
                   f"{c['dim']}~{c['reset']}"
            name = mc.get("client", "?").ljust(14)
            path = mc.get("path", "?")
            print(f"    {icon} {name} → {c['dim']}{path}{c['reset']}")

    errors = results.get("errors", [])
    if errors:
        print(f"\n  {c['red']}Errors:{c['reset']}")
        for err in errors:
            print(f"    • {err}")

    if results.get("success"):
        print(f"\n  {c['bold']}Next Steps:{c['reset']}")
        print(f"  1. Restart your MCP client (Claude Desktop / Cursor / VS Code)")
        print(f"  2. Ask your agent: {c['cyan']}\"Check my Patreon connection\"{c['reset']}")
        print(f"     → Tool: {c['green']}patreon_check_connection{c['reset']}")
        print(f"  3. Get your campaign overview:")
        print(f"     → Tool: {c['green']}campaign_get_overview{c['reset']}")

    print(divider)
    print(f"  Documentation: https://github.com/nuspy/patreonskills/blob/main/README.html")
    print(divider + "\n")


def write_output_json(results: dict, output_path: str) -> None:
    """Write structured result JSON to output_path for agent consumption."""
    try:
        Path(output_path).write_text(json.dumps(results, indent=2, default=str))
        log(f"Result JSON written to {output_path}", "ok")
    except OSError as e:
        log(f"Could not write output JSON to {output_path}: {e}", "warn")


# ── Main Orchestrator ──────────────────────────────────────────────────────────

def main() -> None:
    global _quiet

    args = parse_args()
    _quiet = args.quiet

    results: dict = {
        "success": False,
        "steps": {},
        "install_dir": None,
        "python_exe": None,
        "token_stored": False,
        "mcp_clients": [],
        "connection_test": None,
        "errors": [],
    }

    if args.dry_run:
        log("DRY-RUN mode — no changes will be made", "warn")

    # ── Step 1: Python version check ──────────────────────────────────────────
    log_section("Checking prerequisites")
    results["steps"]["python_check"] = check_python_version()

    # ── Step 2: Resolve install directory ─────────────────────────────────────
    if args.local_path:
        install_dir, clone_result = use_local_path(args.local_path)
        results["steps"]["source"] = clone_result
    else:
        install_dir = Path(args.dir).expanduser().resolve()
        log_section("Cloning repository")
        results["steps"]["clone"] = clone_or_update(
            args.repo, install_dir, args.branch, args.dry_run
        )

    results["install_dir"] = str(install_dir)

    # ── Step 3: Create venv (optional) ────────────────────────────────────────
    if args.venv:
        log_section("Creating virtual environment")
        venv_python = create_venv(install_dir, args.dry_run)
        python_exe = str(venv_python)
        results["steps"]["venv"] = {"path": str(venv_python.parent.parent)}
    else:
        python_exe = resolve_python_executable()
        results["steps"]["venv"] = {"skipped": True}

    results["python_exe"] = python_exe

    # ── Step 4: Install requirements ──────────────────────────────────────────
    if not args.no_pip:
        log_section("Installing dependencies")
        results["steps"]["pip"] = install_requirements(install_dir, python_exe, args.dry_run)

    # ── Step 5: Install Playwright (if requested) ─────────────────────────────
    if args.playwright and not args.no_playwright:
        log_section("Installing Playwright")
        results["steps"]["playwright"] = install_playwright(python_exe, args.dry_run)

    # ── Step 6: Store credentials ─────────────────────────────────────────────
    log_section("Storing credentials")
    token = resolve_token(args)
    cred_result = store_credentials(token, args, install_dir, args.dry_run)
    results["steps"]["credentials"] = cred_result
    results["token_stored"] = True

    # ── Step 7: Configure MCP clients ─────────────────────────────────────────
    if not args.no_mcp:
        log_section("Configuring MCP clients")

        server_entry = build_mcp_server_entry(install_dir, python_exe, token)

        if args.client:
            target_clients = [c.strip().lower() for c in args.client.split(",")]
        else:
            target_clients = detect_existing_mcp_clients()
            if not target_clients:
                log("No MCP client configs detected on this system.", "warn")
                log("Use --client claude|cursor|vscode to configure explicitly.", "info")

        for client_name in target_clients:
            if client_name == "custom":
                if not args.mcp_config_path:
                    log("--mcp-config-path required when --client=custom", "error")
                    continue
                config_path = Path(args.mcp_config_path).expanduser()
            elif client_name in MCP_CONFIG_PATHS:
                config_path = MCP_CONFIG_PATHS[client_name]
            else:
                log(f"Unknown client '{client_name}'. Supported: claude, cursor, vscode, custom", "warn")
                continue

            mc_result = configure_mcp_client(
                client_name, config_path, server_entry, args.dry_run, args.force
            )
            results["mcp_clients"].append(mc_result)

    # ── Step 8: Connection test ────────────────────────────────────────────────
    if not args.no_verify and not args.dry_run:
        log_section("Testing connection")
        test_result = run_connection_test(install_dir, python_exe)
        results["connection_test"] = test_result
        if not test_result["success"]:
            results["errors"].append(f"Connection test failed: {test_result.get('error')}")

    # ── Step 9: Finish ─────────────────────────────────────────────────────────
    results["success"] = True

    print_summary(results)

    if args.output_json:
        write_output_json(results, args.output_json)

    sys.exit(0)


if __name__ == "__main__":
    main()
