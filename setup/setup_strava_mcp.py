#!/usr/bin/env python3
"""
Automated setup tool for Strava MCP integration with Claude Desktop
Uses secure backend service for token exchange.
"""

import os
import sys
import json
import shutil
import platform
import subprocess
import webbrowser
import requests
import time
from pathlib import Path
from typing import Optional
import tempfile
import signal


# ANSI colors for better UX
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


def log(message: str, color: str = Colors.RESET):
    print(f"{color}{message}{Colors.RESET}")


def ask_question(question: str) -> str:
    return input(f"{question}").strip()


def run_command(command: str, cwd: Optional[str] = None, check: bool = True) -> bool:
    """Execute a shell command"""
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
    """Get the Claude Desktop config file path"""
    system = platform.system()
    home = Path.home()

    if system == "Darwin":  # macOS
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    elif system == "Windows":
        return home / "AppData/Roaming/Claude/claude_desktop_config.json"
    else:  # Linux
        return home / ".config/claude/claude_desktop_config.json"


def update_claude_config(mcp_path: Path, access_token: str, refresh_token: str) -> bool:
    """Update Claude Desktop configuration"""
    config_path = get_claude_config_path()
    config_dir = config_path.parent

    # Create config directory if it doesn't exist
    config_dir.mkdir(parents=True, exist_ok=True)

    config = {}

    # Read existing config if it exists
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except Exception:
            log(
                "Warning: Could not parse existing Claude config, creating new one",
                Colors.YELLOW,
            )

    # Initialize mcpServers if it doesn't exist
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    # Add Strava MCP configuration
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

    # Write updated config
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        log(f"✅ Claude config updated at: {config_path}", Colors.GREEN)
        return True
    except Exception as e:
        log(f"❌ Failed to update Claude config: {e}", Colors.RED)
        return False


def authenticate_with_strava() -> tuple[Optional[str], Optional[str]]:
    """Authenticate with Strava using the backend service"""
    log("\n🔐 Strava Authentication", Colors.BOLD)
    log("Opening browser for Strava authentication...")
    log("This will use a secure backend service to handle token exchange.")

    # Prepare authorization URL pointing to our backend service
    redirect_uri = f"{TOKEN_SERVICE_URL}/callback"
    auth_url = (
        f"https://www.strava.com/oauth/authorize?"
        f"client_id={CLIENT_ID}&"
        f"response_type=code&"
        f"redirect_uri={redirect_uri}&"
        f"approval_prompt=auto&"
        f"scope=activity:read_all,profile:read_all"
    )

    log(f"\nOpening: {auth_url}")
    log("\nPlease:")
    log("1. Complete the authentication in your browser")
    log("2. After success, copy the tokens from the page")
    log("3. Return here to continue setup")

    # Open browser
    webbrowser.open(auth_url)

    # Manual token input as fallback
    log("\n📋 After authentication, you should see a success page with your tokens.")
    log("Please copy the tokens from that page:")

    access_token = ask_question("\nPaste your access_token: ")
    refresh_token = ask_question("Paste your refresh_token: ")

    if not access_token or not refresh_token:
        log("❌ Both access_token and refresh_token are required", Colors.RED)
        return None, None

    # Verify tokens work
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(
            "https://www.strava.com/api/v3/athlete", headers=headers, timeout=10
        )

        if response.status_code == 200:
            athlete = response.json()
            log(
                f"✅ Authentication successful! Welcome, {athlete.get('firstname', 'athlete')}!",
                Colors.GREEN,
            )
            return access_token, refresh_token
        else:
            log("❌ Token verification failed", Colors.RED)
            return None, None

    except Exception as e:
        log(f"⚠️  Could not verify tokens: {e}", Colors.YELLOW)
        log("Proceeding anyway...", Colors.YELLOW)
        return access_token, refresh_token


def setup_virtual_environment(install_path: Path) -> bool:
    """Set up Python virtual environment"""
    venv_path = install_path / "venv"

    log("🐍 Setting up Python virtual environment...", Colors.BLUE)

    # Create virtual environment
    if not run_command(f"{sys.executable} -m venv {venv_path}", str(install_path)):
        return False

    # Get the correct python executable for the venv
    if platform.system() == "Windows":
        python_exe = venv_path / "Scripts" / "python.exe"
        pip_exe = venv_path / "Scripts" / "pip.exe"
    else:
        python_exe = venv_path / "bin" / "python"
        pip_exe = venv_path / "bin" / "pip"

    # Upgrade pip
    if not run_command(f"{python_exe} -m pip install --upgrade pip", str(install_path)):
        log("⚠️  Failed to upgrade pip, continuing anyway", Colors.YELLOW)

    # Install requirements
    if not run_command(f"{pip_exe} install -r requirements.txt", str(install_path)):
        return False

    log("✅ Virtual environment setup complete", Colors.GREEN)
    return True


def run_data_sync(install_path: Path, access_token: str, refresh_token: str) -> bool:
    """Run the initial data sync"""
    log("\n📊 Downloading your Strava data...", Colors.BLUE)

    # Create temporary .env file for sync
    env_content = f"""STRAVA_CLIENT_ID={CLIENT_ID}
STRAVA_REFRESH_TOKEN={refresh_token}
STRAVA_TOKEN_SERVICE_URL={TOKEN_SERVICE_URL}
STRAVA_DB_PATH={install_path / "strava_data.db"}
"""

    env_path = install_path / ".env"
    with open(env_path, "w") as f:
        f.write(env_content)

    # Run sync script
    python_exe = (
        install_path
        / "venv"
        / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    )

    # Use --pages 5 to limit initial sync (500 activities max)
    sync_success = run_command(
        f'"{python_exe}" strava-sync.py --pages 5', str(install_path)
    )

    if sync_success:
        log("✅ Initial data sync completed", Colors.GREEN)
    else:
        log("⚠️  Data sync had issues, but you can retry later", Colors.YELLOW)
        log(f'To retry: cd "{install_path}" && python strava-sync.py', Colors.BLUE)

    return sync_success


def restart_claude_desktop() -> bool:
    """Restart Claude Desktop application"""
    system = platform.system()

    try:
        log("🔄 Attempting to restart Claude Desktop...", Colors.BLUE)

        if system == "Darwin":  # macOS
            subprocess.run(["pkill", "-f", "Claude"], check=False, capture_output=True)
            time.sleep(2)
            subprocess.run(
                ["open", "/Applications/Claude.app"], check=False, capture_output=True
            )

        elif system == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/IM", "Claude.exe"],
                check=False,
                capture_output=True,
            )
            time.sleep(2)
            # Try common installation paths
            for path in [
                Path.home() / "AppData/Local/Claude/Claude.exe",
                Path("C:/Program Files/Claude/Claude.exe"),
            ]:
                if path.exists():
                    subprocess.Popen(
                        [str(path)], creationflags=subprocess.DETACHED_PROCESS
                    )
                    break
        else:  # Linux
            subprocess.run(["pkill", "-f", "claude"], check=False, capture_output=True)
            time.sleep(2)
            subprocess.Popen(["claude"])

        log("  → Claude Desktop restarted", Colors.GREEN)
        return True

    except Exception as e:
        log(f"❌ Failed to restart Claude Desktop: {e}", Colors.RED)
        return False


def main():
    """Main setup function"""

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        log("\n\n⏹️  Setup interrupted by user", Colors.YELLOW)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    log(f"{Colors.BOLD}🏃 Strava MCP Setup Tool{Colors.RESET}")
    log("This tool will set up the Strava MCP for Claude Desktop\n")
    log("🔐 Uses secure backend service for token exchange (no client secrets exposed)")

    # Step 1: Choose installation directory
    default_path = Path.home() / ".claude-mcps" / "strava-mcp"
    log(f"Default installation path: {default_path}")
    custom_path = ask_question("Press Enter for default path, or type a custom path: ")
    install_path = Path(custom_path) if custom_path else default_path

    # Step 2: Create directory and download repo
    log("\n📦 Setting up installation directory...")
    install_path.mkdir(parents=True, exist_ok=True)

    log("\n⬇️  Downloading Strava MCP from GitHub...")
    if not run_command(f"git clone {REPO_URL} .", str(install_path)):
        log(
            "❌ Failed to clone repository. Please check the repo URL and try again.",
            Colors.RED,
        )
        sys.exit(1)

    # Step 3: Set up Python environment
    if not setup_virtual_environment(install_path):
        log("❌ Failed to set up Python environment", Colors.RED)
        sys.exit(1)

    # Step 4: Authenticate with Strava
    access_token, refresh_token = authenticate_with_strava()
    if not access_token or not refresh_token:
        log("❌ Authentication failed", Colors.RED)
        sys.exit(1)

    # Step 5: Run initial data sync
    sync_success = run_data_sync(install_path, access_token, refresh_token)

    # Step 6: Update Claude config
    log("\n🔧 Updating Claude Desktop configuration...")
    config_success = update_claude_config(install_path, access_token, refresh_token)
    if not config_success:
        log("❌ Failed to update Claude config automatically.", Colors.RED)
        sys.exit(1)

    # Step 7: Ask about restart
    log("\n🎉 Setup completed successfully!", Colors.GREEN)
    log("\n🔄 Claude Desktop Restart", Colors.BOLD)
    log("To use the Strava MCP, Claude Desktop needs to be restarted.")
    restart_choice = ask_question(
        "Would you like to restart Claude Desktop now? (y/n): "
    )

    if restart_choice.lower().startswith("y"):
        restart_success = restart_claude_desktop()
        if restart_success:
            log("\n✅ Claude Desktop has been restarted!", Colors.GREEN)
            log(
                "The Strava MCP should now be available in your conversations.",
                Colors.GREEN,
            )
        else:
            log(
                "\n⚠️  Automatic restart failed. Please restart Claude Desktop manually.",
                Colors.YELLOW,
            )
    else:
        log("\n📝 Manual restart required:", Colors.YELLOW)
        log("Please restart Claude Desktop when you're ready to use the Strava MCP.")

    # Final summary
    log("\n📋 Summary:", Colors.BOLD)
    log(f"✅ Strava MCP installed: {install_path}")
    log("✅ Claude configuration updated")
    log("✅ Secure authentication completed")
    log("✅ Ready to use!")

    log("\n🛠️  Useful commands:", Colors.BLUE)
    log(f'- Update data: cd "{install_path}" && python strava-sync.py')
    log(f'- View config: cat "{get_claude_config_path()}"')
    log(f'- Uninstall: Remove "{install_path}" and update Claude config')

    log("\n💡 Try asking Claude:", Colors.GREEN)
    log('  "Show me my recent Strava activities"')
    log('  "What\'s my average running pace this month?"')
    log('  "Create a training summary from my data"')

    log(f"\n🔗 Backend service: {TOKEN_SERVICE_URL}")
    log(f"🔗 Source code: {REPO_URL}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n\n⏹️  Setup interrupted by user", Colors.YELLOW)
        sys.exit(0)
    except Exception as e:
        log(f"\n❌ Setup failed: {e}", Colors.RED)
        sys.exit(1)
