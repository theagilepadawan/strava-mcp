#!/usr/bin/env python3
"""
Automated setup tool for Strava MCP integration with Claude Desktop.
Designed for use with pipx or standalone execution.
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


# ANSI terminal colors
class Colors:
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


# Configuration
TOKEN_SERVICE_URL = "https://strava-mcp-backend.vercel.app"
CLIENT_ID = "26565"
REPO_URL = "https://github.com/theagilepadawan/strava-mcp.git"

# Determine install path relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent


def log(message: str, color: str = Colors.RESET):
    print(f"{color}{message}{Colors.RESET}")


def ask_question(question: str) -> str:
    return input(f"{question}").strip()


def run_command(command: str, cwd: Optional[str] = None, check: bool = True) -> bool:
    try:
        log(f"Executing: {command}", Colors.BLUE)
        result = subprocess.run(
            command, shell=True, cwd=cwd, check=check, capture_output=False
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        log(f"Error executing command: {command}", Colors.RED)
        log(str(e), Colors.RED)
        return False


def get_claude_config_path() -> Path:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    elif system == "Windows":
        return home / "AppData/Roaming/Claude/claude_desktop_config.json"
    else:
        return home / ".config/claude/claude_desktop_config.json"


def update_claude_config(mcp_path: Path, access_token: str, refresh_token: str) -> bool:
    config_path = get_claude_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except Exception:
            log("⚠️ Failed to parse existing config, will overwrite.", Colors.YELLOW)

    config.setdefault("mcpServers", {})
    config["mcpServers"]["strava-mcp"] = {
        "command": "python",
        "args": [str(mcp_path / "strava-mcp.py")],
        "env": {
            "STRAVA_CLIENT_ID": CLIENT_ID,
            "STRAVA_REFRESH_TOKEN": refresh_token,
            "STRAVA_TOKEN_SERVICE_URL": TOKEN_SERVICE_URL,
            "STRAVA_DB_PATH": str(mcp_path / "strava_data.db"),
        },
    }

    try:
        config_path.write_text(json.dumps(config, indent=2))
        log(f"✅ Claude config updated: {config_path}", Colors.GREEN)
        return True
    except Exception as e:
        log(f"❌ Failed to write config: {e}", Colors.RED)
        return False


def authenticate_with_strava() -> tuple[Optional[str], Optional[str]]:
    log("\n🔐 Strava Authentication", Colors.BOLD)
    redirect_uri = f"{TOKEN_SERVICE_URL}/callback"
    auth_url = (
        f"https://www.strava.com/oauth/authorize?"
        f"client_id={CLIENT_ID}&response_type=code&redirect_uri={redirect_uri}"
        f"&approval_prompt=auto&scope=activity:read_all,profile:read_all"
    )

    webbrowser.open(auth_url)
    log("➡️ Complete authentication in browser, then paste tokens below.")

    access_token = ask_question("Paste access_token: ")
    refresh_token = ask_question("Paste refresh_token: ")

    if not access_token or not refresh_token:
        log("❌ Missing tokens", Colors.RED)
        return None, None

    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        r = requests.get("https://www.strava.com/api/v3/athlete", headers=headers)
        if r.status_code == 200:
            name = r.json().get("firstname", "athlete")
            log(f"✅ Welcome, {name}!", Colors.GREEN)
            return access_token, refresh_token
        else:
            log("❌ Token validation failed", Colors.RED)
            return None, None
    except Exception as e:
        log(f"⚠️ Token check failed: {e}", Colors.YELLOW)
        return access_token, refresh_token


def setup_virtual_environment(install_path: Path) -> bool:
    venv = install_path / "venv"
    if not run_command(f"{sys.executable} -m venv {venv}", str(install_path)):
        return False

    if platform.system() == "Windows":
        python = venv / "Scripts" / "python.exe"
        pip = venv / "Scripts" / "pip.exe"
    else:
        python = venv / "bin" / "python"
        pip = venv / "bin" / "pip"

    run_command(f"{python} -m pip install --upgrade pip", str(install_path))

    requirements = install_path / "requirements.txt"
    if not requirements.exists():
        log(f"❌ requirements.txt not found at {requirements}", Colors.RED)
        return False

    return run_command(f"{pip} install -r {requirements}", str(install_path))


def run_data_sync(install_path: Path, access_token: str, refresh_token: str) -> bool:
    env_file = install_path / ".env"
    env_file.write_text(f"""STRAVA_CLIENT_ID={CLIENT_ID}
STRAVA_REFRESH_TOKEN={refresh_token}
STRAVA_TOKEN_SERVICE_URL={TOKEN_SERVICE_URL}
STRAVA_DB_PATH={install_path / "strava_data.db"}
""")

    python = (
        install_path
        / "venv"
        / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    )
    return run_command(f'"{python}" strava-sync.py --pages 5', str(install_path))


def restart_claude_desktop():
    try:
        log("🔄 Restarting Claude Desktop...", Colors.BLUE)
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/IM", "Claude.exe"], check=False)
            time.sleep(1)
            for path in [
                Path.home() / "AppData/Local/Claude/Claude.exe",
                Path("C:/Program Files/Claude/Claude.exe"),
            ]:
                if path.exists():
                    subprocess.Popen(
                        [str(path)], creationflags=subprocess.DETACHED_PROCESS
                    )
                    break
        elif platform.system() == "Darwin":
            subprocess.run(["pkill", "-f", "Claude"], check=False)
            time.sleep(1)
            subprocess.run(["open", "/Applications/Claude.app"], check=False)
        else:
            subprocess.run(["pkill", "-f", "claude"], check=False)
            time.sleep(1)
            subprocess.Popen(["claude"])
        log("✅ Claude restarted", Colors.GREEN)
    except Exception as e:
        log(f"⚠️ Failed to restart Claude: {e}", Colors.YELLOW)


def main():
    signal.signal(
        signal.SIGINT, lambda *_: (log("\n⏹️  Interrupted", Colors.YELLOW), sys.exit(0))
    )

    log(f"{Colors.BOLD}🏃 Strava MCP Setup Tool{Colors.RESET}")
    install_path = SCRIPT_DIR  # pipx compatibility fix

    log(f"📦 Installing in: {install_path}")
    if not setup_virtual_environment(install_path):
        log("❌ Virtual environment setup failed", Colors.RED)
        sys.exit(1)

    access_token, refresh_token = authenticate_with_strava()
    if not access_token:
        sys.exit(1)

    run_data_sync(install_path, access_token, refresh_token)
    update_claude_config(install_path, access_token, refresh_token)

    if ask_question("Restart Claude Desktop now? (y/n): ").lower().startswith("y"):
        restart_claude_desktop()

    log("\n🎉 Setup complete!", Colors.GREEN)
    log(f"➡️ You can now ask Claude: 'Show my recent Strava runs'")
    log(f"📁 Installed to: {install_path}")
    log(f"⚙️ Config updated: {get_claude_config_path()}")


if __name__ == "__main__":
    main()
