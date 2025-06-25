#!/usr/bin/env python3
"""
Automated setup tool for Strava MCP integration with Claude Desktop.
Now pipx-compatible with dynamic requirements.txt path resolution.
"""

import sys
import json
import platform
import subprocess
import webbrowser
import requests
import time
import signal
from pathlib import Path
from typing import Optional


# ANSI colors
class Colors:
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


# Config
TOKEN_SERVICE_URL = "https://strava-mcp-backend.vercel.app"
CLIENT_ID = "26565"

# Resolve install path even inside pipx
SCRIPT_PATH = Path(__file__).resolve()
INSTALL_PATH = SCRIPT_PATH
while INSTALL_PATH.name != "site-packages" and INSTALL_PATH != INSTALL_PATH.parent:
    INSTALL_PATH = INSTALL_PATH.parent
# We're now in the venv's site-packages folder — assume the repo root is one level up
INSTALL_PATH = INSTALL_PATH.parent


def log(msg, color=Colors.RESET):
    print(f"{color}{msg}{Colors.RESET}")


def ask(question: str) -> str:
    return input(f"{question}").strip()


def run(cmd: str, cwd: Optional[Path] = None) -> bool:
    try:
        log(f"Executing: {cmd}", Colors.BLUE)
        result = subprocess.run(cmd, shell=True, cwd=cwd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        log(f"❌ Command failed: {cmd}", Colors.RED)
        log(str(e), Colors.RED)
        return False


def setup_virtual_env(install_path: Path) -> bool:
    venv = install_path / "venv"
    if not run(f"{sys.executable} -m venv {venv}"):
        return False

    if platform.system() == "Windows":
        python = venv / "Scripts" / "python.exe"
        pip = venv / "Scripts" / "pip.exe"
    else:
        python = venv / "bin" / "python"
        pip = venv / "bin" / "pip"

    run(f"{python} -m pip install --upgrade pip")

    req = install_path / "requirements.txt"
    if not req.exists():
        log(f"❌ requirements.txt not found at: {req}", Colors.RED)
        return False

    return run(f"{pip} install -r {req}", cwd=install_path)


def authenticate() -> tuple[Optional[str], Optional[str]]:
    redirect_uri = f"{TOKEN_SERVICE_URL}/callback"
    auth_url = (
        f"https://www.strava.com/oauth/authorize?"
        f"client_id={CLIENT_ID}&response_type=code&redirect_uri={redirect_uri}"
        f"&approval_prompt=auto&scope=activity:read_all,profile:read_all"
    )

    log("🌐 Opening browser to authenticate with Strava")
    webbrowser.open(auth_url)
    log("➡️ Complete auth and paste your tokens here")

    access = ask("Access token: ")
    refresh = ask("Refresh token: ")

    if not access or not refresh:
        return None, None

    try:
        r = requests.get(
            "https://www.strava.com/api/v3/athlete",
            headers={"Authorization": f"Bearer {access}"},
        )
        if r.status_code == 200:
            log(
                f"✅ Auth successful. Welcome, {r.json().get('firstname')}",
                Colors.GREEN,
            )
            return access, refresh
        else:
            log("❌ Token rejected", Colors.RED)
            return None, None
    except Exception as e:
        log(f"⚠️ Couldn't verify token: {e}", Colors.YELLOW)
        return access, refresh


def sync_data(install_path: Path, access: str, refresh: str):
    env_path = install_path / ".env"
    env_path.write_text(f"""STRAVA_CLIENT_ID={CLIENT_ID}
STRAVA_REFRESH_TOKEN={refresh}
STRAVA_TOKEN_SERVICE_URL={TOKEN_SERVICE_URL}
STRAVA_DB_PATH={install_path / "strava_data.db"}
""")

    python = (
        install_path
        / "venv"
        / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    )
    return run(f'"{python}" strava-sync.py --pages 5', cwd=install_path)


def get_claude_config_path() -> Path:
    home = Path.home()
    if platform.system() == "Windows":
        return home / "AppData/Roaming/Claude/claude_desktop_config.json"
    elif platform.system() == "Darwin":
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    else:
        return home / ".config/claude/claude_desktop_config.json"


def update_config(path: Path, access: str, refresh: str):
    config_path = get_claude_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
    except:
        config = {}

    config.setdefault("mcpServers", {})
    config["mcpServers"]["strava-mcp"] = {
        "command": "python",
        "args": [str(path / "strava-mcp.py")],
        "env": {
            "STRAVA_CLIENT_ID": CLIENT_ID,
            "STRAVA_REFRESH_TOKEN": refresh,
            "STRAVA_TOKEN_SERVICE_URL": TOKEN_SERVICE_URL,
            "STRAVA_DB_PATH": str(path / "strava_data.db"),
        },
    }

    config_path.write_text(json.dumps(config, indent=2))
    log(f"✅ Claude config written to: {config_path}", Colors.GREEN)


def restart_claude():
    try:
        log("🔄 Restarting Claude...", Colors.BLUE)
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/IM", "Claude.exe"], check=False)
            time.sleep(1)
            exe = Path.home() / "AppData/Local/Claude/Claude.exe"
            if exe.exists():
                subprocess.Popen([str(exe)], creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.run(["pkill", "-f", "claude"], check=False)
            time.sleep(1)
            subprocess.Popen(["claude"])
        log("✅ Restart triggered", Colors.GREEN)
    except Exception as e:
        log(f"⚠️ Could not restart Claude: {e}", Colors.YELLOW)


def main():
    signal.signal(
        signal.SIGINT,
        lambda *_: (log("⏹️  Aborted by user", Colors.YELLOW), sys.exit(0)),
    )

    log(f"{Colors.BOLD}🏃 Strava MCP Setup Tool{Colors.RESET}")
    log(f"📦 Installing in: {INSTALL_PATH}")

    if not setup_virtual_env(INSTALL_PATH):
        sys.exit(1)

    access, refresh = authenticate()
    if not access or not refresh:
        sys.exit(1)

    sync_data(INSTALL_PATH, access, refresh)
    update_config(INSTALL_PATH, access, refresh)

    if ask("Restart Claude now? (y/n): ").lower().startswith("y"):
        restart_claude()

    log("\n🎉 Done! You can now talk to Claude about your Strava data.", Colors.GREEN)


if __name__ == "__main__":
    main()
