#!/usr/bin/env python3
"""
Strava Sync - Data Initialization Script

This script handles the initial setup and synchronization of Strava data to a local SQLite database.
Uses the secure backend service for token management.
"""

import os
import json
import sqlite3
import requests
import argparse
import logging
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

# Configuration from environment variables
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "26565")
REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")
TOKEN_SERVICE_URL = os.getenv(
    "STRAVA_TOKEN_SERVICE_URL", "https://strava-mcp-backend.vercel.app"
)
DB_PATH = os.getenv(
    "STRAVA_DB_PATH",
    os.path.join(os.path.expanduser("~"), ".strava_mcp", "strava_data.db"),
)
REQUEST_TIMEOUT = int(os.getenv("STRAVA_REQUEST_TIMEOUT", "30"))


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


def get_stored_token(conn) -> Optional[Dict[str, any]]:
    """Get the most recent stored token"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT access_token, refresh_token, expires_at FROM auth_token ORDER BY created_at DESC LIMIT 1"
    )
    token_row = cursor.fetchone()

    if not token_row:
        return None

    return {
        "access_token": token_row[0],
        "refresh_token": token_row[1],
        "expires_at": token_row[2],
    }


def refresh_strava_access_token(refresh_token: str) -> Dict[str, any]:
    """Refresh access token using the backend service"""
    try:
        logger.info("Refreshing access token using backend service...")

        response = requests.post(
            f"{TOKEN_SERVICE_URL}/refresh-token",
            json={"refresh_token": refresh_token},
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.text}")

        data = response.json()
        logger.info("Token refresh successful")

        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": data["expires_at"],
        }

    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise Exception(f"Failed to refresh Strava token: {str(e)}")


def ensure_valid_token(conn) -> str:
    """Ensure we have a valid access token"""
    # Try to get stored token
    stored_token = get_stored_token(conn)

    if stored_token:
        # Check if token is still valid (with 60 second buffer)
        if stored_token["expires_at"] > datetime.now().timestamp() + 60:
            logger.info("Using existing valid token")
            return stored_token["access_token"]
        else:
            logger.info("Stored token expired, refreshing...")
            # Use stored refresh token to get new token
            refresh_token = stored_token["refresh_token"]
    else:
        # No stored token, use refresh token from environment
        if not REFRESH_TOKEN:
            raise ValueError(
                "No refresh token available. Please run the setup tool first."
            )
        refresh_token = REFRESH_TOKEN

    # Refresh the token using backend service
    new_token = refresh_strava_access_token(refresh_token)

    # Store the new token
    store_token(
        conn,
        new_token["access_token"],
        new_token["refresh_token"],
        new_token["expires_at"],
    )

    return new_token["access_token"]


def store_token(conn, access_token, refresh_token, expires_at):
    """Store the auth token in the database"""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO auth_token (access_token, refresh_token, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (access_token, refresh_token, expires_at, int(datetime.now().timestamp())),
    )
    conn.commit()
    logger.info("Stored new token in database")


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


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Sync Strava data to local database")
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
        "--token-service-url", help="Token service URL (overrides .env)"
    )

    args = parser.parse_args()

    # Override with command-line arguments if provided
    db_path = args.db_path or DB_PATH
    token_service_url = args.token_service_url or TOKEN_SERVICE_URL

    # Validate configuration
    if not CLIENT_ID:
        logger.error("Missing STRAVA_CLIENT_ID. Please check your .env file.")
        return 1

    if not token_service_url:
        logger.error("Missing STRAVA_TOKEN_SERVICE_URL. Please check your .env file.")
        return 1

    if not REFRESH_TOKEN:
        logger.error(
            "Missing STRAVA_REFRESH_TOKEN. Please run the setup tool first to get your tokens."
        )
        return 1

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    logger.info(f"Connecting to database at {db_path}")
    logger.info(f"Using token service: {token_service_url}")

    conn = sqlite3.connect(db_path)

    # Initialize database schema
    init_db(conn)

    try:
        # Get valid access token (refreshes if needed)
        access_token = ensure_valid_token(conn)

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

            # Print summary
            print(f"\nSync complete!")
            print(f"Athlete: {athlete.get('firstname')} {athlete.get('lastname')}")
            print(f"Activities: {activity_count}")
            print(f"Database: {db_path}")
            print("\nYou can now use the Strava MCP server to access this data.")

    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    exit(main())
