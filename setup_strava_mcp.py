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
import toml
from pathlib import Path
from typing import Optional
import urllib.parse


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
REPO_URL = "https://github.com/theagilepadawan/strava-mcp.git"


def log(msg, color=Colors.RESET):
    print(f"{color}{msg}{Colors.RESET}")


def ask(question: str) -> str:
    return input(f"{question}").strip()


def run(cmd: str, cwd: Optional[Path] = None) -> bool:
    try:
        log(f"Executing: {cmd}", Colors.BLUE)
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, check=True, capture_output=True, text=True
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        log(f"❌ Command failed: {cmd}", Colors.RED)
        log(f"  stdout: {e.stdout}", Colors.RED)
        log(f"  stderr: {e.stderr}", Colors.RED)
        return False


def setup_virtual_env(install_path: Path) -> bool:
    venv = install_path / "venv"
    log(f"🐍 Setting up Python virtual environment in: {venv}", Colors.BLUE)
    if not run(f'"{sys.executable}" -m venv "{venv}"'):
        return False

    if platform.system() == "Windows":
        python = venv / "Scripts" / "python.exe"
        pip = venv / "Scripts" / "pip.exe"
    else:
        python = venv / "bin" / "python"
        pip = venv / "bin" / "pip"

    run(f'"{python}" -m pip install --upgrade pip')

    proj_file = install_path / "pyproject.toml"
    if not proj_file.exists():
        log(f"❌ pyproject.toml not found at: {proj_file}", Colors.RED)
        return False

    config = toml.load(proj_file)
    dependencies = (
        config.get("project", {}).get("optional-dependencies", {}).get("app", [])
    )

    if not dependencies:
        log("✅ No app dependencies found to install.", Colors.GREEN)
        return True

    dep_string = " ".join(f'"{dep}"' for dep in dependencies)
    log(f"📦 Installing app dependencies: {dep_string}", Colors.BLUE)

    return run(f'"{pip}" install {dep_string}', cwd=install_path)


def authenticate() -> tuple[Optional[str], Optional[str]]:
    redirect_uri = f"{TOKEN_SERVICE_URL}/callback"
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": f"{TOKEN_SERVICE_URL}/callback",
        "approval_prompt": "auto",
        "scope": "activity:read_all,profile:read_all",
    }

    auth_url = "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(
        params
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
    return run(f'"{python}" strava-sync.py --full-sync', cwd=install_path)


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

    # Step 1: Choose installation directory
    default_path = Path.home() / ".claude-mcps" / "strava-mcp"
    install_path_str = ask(
        f"Press Enter to install in [{default_path}], or type a custom path: "
    )
    install_path = Path(install_path_str) if install_path_str else default_path

    # Step 2: Create directory and download repo
    if (install_path / ".git").is_dir():
        log(f"✅ Using existing repository at {install_path}", Colors.GREEN)
    elif install_path.exists() and any(install_path.iterdir()):
        log(f"❌ Directory '{install_path}' is not empty.", Colors.RED)
        sys.exit(1)
    else:
        log(f"⬇️  Downloading Strava MCP to {install_path}...", Colors.BLUE)
        install_path.parent.mkdir(parents=True, exist_ok=True)
        if not run(f'git clone {REPO_URL} "{install_path}"'):
            log("❌ Failed to clone repository.", Colors.RED)
            sys.exit(1)

    if not setup_virtual_env(install_path):
        sys.exit(1)

    access, refresh = authenticate()
    if not access or not refresh:
        sys.exit(1)

    sync_data(install_path, access, refresh)
    update_config(install_path, access, refresh)

    if ask("Restart Claude now? (y/n): ").lower().startswith("y"):
        restart_claude()

    log("\n🎉 Done! You can now talk to Claude about your Strava data.", Colors.GREEN)


if __name__ == "__main__":
    main()
