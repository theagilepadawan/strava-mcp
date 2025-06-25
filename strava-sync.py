#!/usr/bin/env python3
"""
Strava Sync - Data Initialization Script

This script handles the initial setup and synchronization of Strava data to a local SQLite database.
Run this script before using the Strava MCP server to fetch and store your data.

Authentication: The script assists in obtaining tokens with activity:read_all scope through OAuth.
"""

import os
import json
import sqlite3
import requests
import argparse
import logging
import webbrowser
import http.server
import socketserver
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("strava_sync")

# Strava API Constants
STRAVA_API_BASE_URL = "https://www.strava.com/api/v3"
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

# Configuration from environment variables
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")
DB_PATH = os.getenv(
    "STRAVA_DB_PATH",
    os.path.join(os.path.expanduser("~"), ".strava_mcp", "strava_data.db"),
)
REQUEST_TIMEOUT = int(os.getenv("STRAVA_REQUEST_TIMEOUT", "30"))
OAUTH_PORT = int(os.getenv("STRAVA_OAUTH_PORT", "8000"))

# Global variable to store authorization code
AUTH_CODE = None


class OAuthHandler(http.server.SimpleHTTPRequestHandler):
    """Handler for OAuth callback"""

    def do_GET(self):
        """Handle GET request"""
        global AUTH_CODE

        # Parse query parameters
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        # Extract authorization code
        if "code" in params:
            AUTH_CODE = params["code"][0]

            # Respond to the browser
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            response = """
            <html>
            <head><title>Strava OAuth Authentication</title></head>
            <body>
                <h1>Authentication Successful!</h1>
                <p>You have successfully authenticated with Strava.</p>
                <p>You can close this browser window and return to the application.</p>
            </body>
            </html>
            """

            self.wfile.write(response.encode("utf-8"))
        else:
            # Authentication failed
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            response = """
            <html>
            <head><title>Strava OAuth Authentication</title></head>
            <body>
                <h1>Authentication Failed</h1>
                <p>Failed to authenticate with Strava. Please try again.</p>
            </body>
            </html>
            """

            self.wfile.write(response.encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress server logs"""
        return


def init_db(conn):
    """Initialize the SQLite database schema"""
    cursor = conn.cursor()

    # Create activities table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY,
        name TEXT,
        type TEXT,
        sport_type TEXT,
        start_date TEXT,
        distance REAL,
        moving_time INTEGER,
        elapsed_time INTEGER,
        total_elevation_gain REAL,
        average_speed REAL,
        max_speed REAL,
        has_heartrate BOOLEAN,
        average_heartrate REAL,
        max_heartrate REAL,
        kudos_count INTEGER,
        achievement_count INTEGER,
        pr_count INTEGER,
        json_data TEXT
    )
    """)

    # Create athlete table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS athlete (
        id INTEGER PRIMARY KEY,
        firstname TEXT,
        lastname TEXT,
        city TEXT,
        state TEXT,
        country TEXT,
        sex TEXT,
        profile TEXT,
        created_at TEXT,
        weight REAL,
        ftp INTEGER,
        json_data TEXT
    )
    """)

    # Create gear table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gear (
        id TEXT PRIMARY KEY,
        name TEXT,
        type TEXT,
        brand_name TEXT,
        model_name TEXT,
        description TEXT,
        distance REAL,
        json_data TEXT
    )
    """)

    # Create token table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auth_token (
        id INTEGER PRIMARY KEY,
        access_token TEXT,
        refresh_token TEXT,
        expires_at INTEGER,
        created_at INTEGER
    )
    """)

    # Create stats table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS athlete_stats (
        id INTEGER PRIMARY KEY,
        athlete_id INTEGER,
        biggest_ride_distance REAL,
        biggest_climb_elevation_gain REAL,
        json_data TEXT,
        updated_at INTEGER
    )
    """)

    # Add indexes for common queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_type ON activities(type)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(start_date)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_activities_distance ON activities(distance)"
    )

    conn.commit()


def authorize_with_strava(client_id=None, port=None):
    """Start OAuth flow with Strava"""
    client_id = client_id or CLIENT_ID
    port = port or OAUTH_PORT

    if not client_id:
        raise ValueError("Missing Strava API Client ID")

    # Prepare authorization URL
    redirect_uri = f"http://localhost:{port}"
    auth_url = (
        f"{STRAVA_AUTH_URL}?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={redirect_uri}&"
        f"approval_prompt=auto&"
        f"scope=activity:read_all,profile:read_all,read_all"
    )

    print("\n==== Strava API Authentication ====")
    print("Opening browser for Strava authentication...")
    print(f"If the browser doesn't open automatically, please go to:\n{auth_url}\n")

    # Open browser to the authorization URL
    webbrowser.open(auth_url)

    # Start simple HTTP server to handle callback
    with socketserver.TCPServer(("", port), OAuthHandler) as httpd:
        print(f"Waiting for authentication on http://localhost:{port}...")
        print("Please authenticate in your browser and authorize the application.")

        # Serve until authorization code is received
        while AUTH_CODE is None:
            httpd.handle_request()

    print("Authentication successful! Received authorization code.")
    return AUTH_CODE


def exchange_code_for_token(client_id, client_secret, code):
    """Exchange authorization code for access token"""
    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        raise Exception(f"Failed to exchange code for token: {response.text}")

    data = response.json()
    return data["access_token"], data["refresh_token"], data["expires_at"]


def get_strava_access_token(client_id=None, client_secret=None, refresh_token=None):
    """Get a fresh access token using refresh token"""
    client_id = client_id or CLIENT_ID
    client_secret = client_secret or CLIENT_SECRET
    refresh_token = refresh_token or REFRESH_TOKEN

    if not client_id or not client_secret:
        raise ValueError(
            "Missing Strava API credentials. Please check your .env file or provide them as parameters."
        )

    # If no refresh token, start OAuth flow
    if not refresh_token:
        logger.info("No refresh token found. Starting OAuth flow...")
        auth_code = authorize_with_strava(client_id)
        return exchange_code_for_token(client_id, client_secret, auth_code)

    # Otherwise, use refresh token to get a new access token
    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        raise Exception(f"Failed to refresh token: {response.text}")

    data = response.json()
    return data["access_token"], data["refresh_token"], data["expires_at"]


def store_token(conn, access_token, refresh_token, expires_at):
    """Store the auth token in the database"""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO auth_token (access_token, refresh_token, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (access_token, refresh_token, expires_at, int(datetime.now().timestamp())),
    )
    conn.commit()


def strava_api_request(method, endpoint, access_token, params=None, data=None):
    """Make a request to the Strava API"""
    url = f"{STRAVA_API_BASE_URL}/{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        if method.lower() == "get":
            response = requests.get(
                url, headers=headers, params=params, timeout=REQUEST_TIMEOUT
            )
        elif method.lower() == "post":
            response = requests.post(
                url, headers=headers, json=data, timeout=REQUEST_TIMEOUT
            )
        elif method.lower() == "put":
            response = requests.put(
                url, headers=headers, json=data, timeout=REQUEST_TIMEOUT
            )
        elif method.lower() == "delete":
            response = requests.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API request error: {e}")
        raise Exception(f"Strava API request failed: {str(e)}")


def fetch_strava_activities(access_token, conn, page_limit=None):
    """Fetch all activities from Strava API"""
    page = 1
    per_page = 100
    all_activities = []
    total_fetched = 0

    logger.info("Fetching activities from Strava API...")

    while True:
        activities = strava_api_request(
            "get",
            "athlete/activities",
            access_token,
            params={"page": page, "per_page": per_page},
        )

        if not activities:
            break

        batch_size = len(activities)
        all_activities.extend(activities)
        total_fetched += batch_size

        logger.info(
            f"Fetched page {page} with {batch_size} activities (total: {total_fetched})"
        )

        page += 1

        if page_limit and page > page_limit:
            logger.info(f"Reached page limit of {page_limit}")
            break

    cursor = conn.cursor()

    for activity_data in all_activities:
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO activities 
                (id, name, type, sport_type, start_date, distance, moving_time, elapsed_time,
                total_elevation_gain, average_speed, max_speed, has_heartrate, 
                average_heartrate, max_heartrate, kudos_count, achievement_count, pr_count, json_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity_data.get("id"),
                    activity_data.get("name", ""),
                    activity_data.get("type", ""),
                    activity_data.get("sport_type"),
                    activity_data.get("start_date", ""),
                    activity_data.get("distance", 0),
                    activity_data.get("moving_time", 0),
                    activity_data.get("elapsed_time", 0),
                    activity_data.get("total_elevation_gain", 0),
                    activity_data.get("average_speed", 0),
                    activity_data.get("max_speed", 0),
                    activity_data.get("has_heartrate", False),
                    activity_data.get("average_heartrate", 0),
                    activity_data.get("max_heartrate", 0),
                    activity_data.get("kudos_count", 0),
                    activity_data.get("achievement_count", 0),
                    activity_data.get("pr_count", 0),
                    json.dumps(activity_data),
                ),
            )
        except Exception as e:
            logger.error(f"Error saving activity {activity_data.get('id')}: {e}")

    conn.commit()
    logger.info(f"Saved {len(all_activities)} activities to database")
    return len(all_activities)


def fetch_strava_athlete(access_token, conn):
    """Fetch athlete data from Strava API"""
    logger.info("Fetching athlete data from Strava API...")
    athlete_data = strava_api_request("get", "athlete", access_token)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO athlete 
        (id, firstname, lastname, city, state, country, sex, profile, created_at, weight, ftp, json_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            athlete_data.get("id"),
            athlete_data.get("firstname", ""),
            athlete_data.get("lastname", ""),
            athlete_data.get("city"),
            athlete_data.get("state"),
            athlete_data.get("country"),
            athlete_data.get("sex"),
            athlete_data.get("profile"),
            athlete_data.get("created_at"),
            athlete_data.get("weight"),
            athlete_data.get("ftp"),
            json.dumps(athlete_data),
        ),
    )
    conn.commit()
    logger.info(
        f"Saved athlete data for {athlete_data.get('firstname')} {athlete_data.get('lastname')}"
    )

    # Fetch and store athlete stats
    try:
        logger.info("Fetching athlete stats...")
        stats_data = strava_api_request(
            "get", f"athletes/{athlete_data.get('id')}/stats", access_token
        )

        cursor.execute(
            """
            INSERT OR REPLACE INTO athlete_stats
            (athlete_id, biggest_ride_distance, biggest_climb_elevation_gain, json_data, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                athlete_data.get("id"),
                stats_data.get("biggest_ride_distance", 0),
                stats_data.get("biggest_climb_elevation_gain", 0),
                json.dumps(stats_data),
                int(datetime.now().timestamp()),
            ),
        )
        conn.commit()
        logger.info("Saved athlete stats")
    except Exception as e:
        logger.error(f"Error fetching athlete stats: {e}")

    # Fetch and store gear
    logger.info("Processing athlete gear...")
    if "bikes" in athlete_data and athlete_data["bikes"]:
        for bike_data in athlete_data["bikes"]:
            cursor.execute(
                """
                INSERT OR REPLACE INTO gear
                (id, name, type, brand_name, model_name, description, distance, json_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bike_data.get("id"),
                    bike_data.get("name", ""),
                    "bike",
                    bike_data.get("brand_name"),
                    bike_data.get("model_name"),
                    bike_data.get("description"),
                    bike_data.get("distance", 0),
                    json.dumps(bike_data),
                ),
            )

    if "shoes" in athlete_data and athlete_data["shoes"]:
        for shoe_data in athlete_data["shoes"]:
            cursor.execute(
                """
                INSERT OR REPLACE INTO gear
                (id, name, type, brand_name, model_name, description, distance, json_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shoe_data.get("id"),
                    shoe_data.get("name", ""),
                    "shoe",
                    shoe_data.get("brand_name"),
                    shoe_data.get("model_name"),
                    shoe_data.get("description"),
                    shoe_data.get("distance", 0),
                    json.dumps(shoe_data),
                ),
            )
    conn.commit()
    gear_count = len(athlete_data.get("bikes", [])) + len(athlete_data.get("shoes", []))
    logger.info(f"Saved {gear_count} gear items")

    return athlete_data


def fetch_activity_details(access_token, activity_id, conn):
    """Fetch and store detailed activity data"""
    logger.info(f"Fetching detailed data for activity {activity_id}...")
    activity_data = strava_api_request("get", f"activities/{activity_id}", access_token)

    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE activities SET
        name=?, type=?, sport_type=?, distance=?, moving_time=?, elapsed_time=?,
        total_elevation_gain=?, average_speed=?, max_speed=?, has_heartrate=?,
        average_heartrate=?, max_heartrate=?, json_data=?
        WHERE id=?
        """,
        (
            activity_data.get("name", ""),
            activity_data.get("type", ""),
            activity_data.get("sport_type"),
            activity_data.get("distance", 0),
            activity_data.get("moving_time", 0),
            activity_data.get("elapsed_time", 0),
            activity_data.get("total_elevation_gain", 0),
            activity_data.get("average_speed", 0),
            activity_data.get("max_speed", 0),
            activity_data.get("has_heartrate", False),
            activity_data.get("average_heartrate", 0),
            activity_data.get("max_heartrate", 0),
            json.dumps(activity_data),
            activity_id,
        ),
    )
    conn.commit()
    logger.info(f"Saved detailed data for activity {activity_id}")
    return activity_data


def print_token_instructions():
    """Print instructions for manually setting up tokens"""
    print("\n=== Manual Token Setup Instructions ===")
    print("If the automatic OAuth flow doesn't work, you can manually get a token:")
    print("\n1. Register your application at https://www.strava.com/settings/api")
    print("2. Set the 'Authorization Callback Domain' to 'localhost'")
    print("\n3. Visit this URL in your browser (replace YOUR_CLIENT_ID):")
    print(
        "   https://www.strava.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost&approval_prompt=auto&scope=activity:read_all,profile:read_all,read_all"
    )
    print("\n4. After authorizing, you'll be redirected to a URL like:")
    print(
        "   http://localhost/?state=&code=AUTHORIZATION_CODE&scope=read,activity:read_all,profile:read_all"
    )
    print("\n5. Copy the 'code' parameter from the URL")
    print("\n6. Exchange the code for tokens using:")
    print(
        "   curl -X POST https://www.strava.com/oauth/token -d client_id=YOUR_CLIENT_ID -d client_secret=YOUR_CLIENT_SECRET -d code=AUTHORIZATION_CODE -d grant_type=authorization_code"
    )
    print("\n7. Store the refresh_token in your .env file as STRAVA_REFRESH_TOKEN")
    print("============================================\n")


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Sync Strava data to local database")
    parser.add_argument("--client-id", help="Strava API client ID (overrides .env)")
    parser.add_argument(
        "--client-secret", help="Strava API client secret (overrides .env)"
    )
    parser.add_argument(
        "--refresh-token", help="Strava API refresh token (overrides .env)"
    )
    parser.add_argument("--db-path", help="Path to SQLite database (overrides .env)")
    parser.add_argument(
        "--full-sync",
        action="store_true",
        help="Fetch all activities (default: recent only)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        help="Limit to this many pages of activities (100 per page)",
    )
    parser.add_argument(
        "--activity-id", type=str, help="Fetch detailed data for specific activity ID"
    )
    parser.add_argument(
        "--oauth-port",
        type=int,
        default=OAUTH_PORT,
        help="Port to use for OAuth callback server",
    )
    parser.add_argument(
        "--manual-auth",
        action="store_true",
        help="Show instructions for manual token setup",
    )

    args = parser.parse_args()

    if args.manual_auth:
        print_token_instructions()
        return 0

    # Override with command-line arguments if provided
    client_id = args.client_id or CLIENT_ID
    client_secret = args.client_secret or CLIENT_SECRET
    refresh_token = args.refresh_token or REFRESH_TOKEN
    db_path = args.db_path or DB_PATH

    if not client_id or not client_secret:
        logger.error(
            "Missing Strava API credentials. Please set them in .env file or provide as arguments."
        )
        return 1

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    logger.info(f"Connecting to database at {db_path}")
    conn = sqlite3.connect(db_path)

    # Initialize database schema
    init_db(conn)

    try:
        # Get fresh access token
        logger.info("Obtaining access token...")
        access_token, new_refresh_token, expires_at = get_strava_access_token(
            client_id, client_secret, refresh_token
        )
        logger.info(
            f"Got access token, expires at {datetime.fromtimestamp(expires_at)}"
        )

        # Store token for later use
        store_token(conn, access_token, new_refresh_token, expires_at)

        if args.activity_id:
            # Fetch detailed data for a specific activity
            fetch_activity_details(access_token, args.activity_id, conn)
        else:
            # Fetch athlete data
            athlete = fetch_strava_athlete(access_token, conn)

            # Fetch activities
            page_limit = None if args.full_sync else args.pages or 30
            activity_count = fetch_strava_activities(access_token, conn, page_limit)

            logger.info(
                f"Sync complete. Fetched data for {athlete.get('firstname')} {athlete.get('lastname')}"
            )
            logger.info(f"Synced {activity_count} activities")
            logger.info(f"New refresh token: {new_refresh_token}")

            # Print summary
            print(f"\nSync complete!")
            print(f"Athlete: {athlete.get('firstname')} {athlete.get('lastname')}")
            print(f"Activities: {activity_count}")
            print(f"Database: {db_path}")
            print(f"New refresh token: {new_refresh_token}")
            print("\nYou can now use the Strava MCP server to access this data.")
            print(f"Add this to your .env file to avoid authentication next time:")
            print(f"STRAVA_REFRESH_TOKEN={new_refresh_token}")

    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    exit(main())
