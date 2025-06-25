#!/usr/bin/env python3
"""
Strava MCP Server

This server provides MCP tools and resources for accessing Strava data stored in a local SQLite database.
Uses secure backend service for token management.
"""

import os
import re
import json
import sqlite3
import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Union, Literal, Callable, TypeVar
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

from pydantic import BaseModel, Field, HttpUrl, validator

from mcp.server.fastmcp import FastMCP

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('strava_mcp')

# Configuration from environment variables
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "26565")
REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")
TOKEN_SERVICE_URL = os.getenv("STRAVA_TOKEN_SERVICE_URL", "https://your-strava-mcp-service.vercel.app")
DB_PATH = os.getenv("STRAVA_DB_PATH", os.path.join(os.path.expanduser("~"), ".strava_mcp", "strava_data.db"))
REQUEST_TIMEOUT = int(os.getenv("STRAVA_REQUEST_TIMEOUT", "30"))

# Strava API Constants
STRAVA_API_BASE_URL = "https://www.strava.com/api/v3"

# ==================== DATABASE CONNECTION MANAGEMENT ====================

@contextmanager
def get_db_connection():
    """
    Context manager for database connections.
    Ensures connections are properly closed after use.
    """
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()

# ==================== PYDANTIC MODELS ====================

# [Keep all the existing Pydantic models from the original script]
class ActivityType(str, Enum):
    ALPINE_SKI = "AlpineSki"
    BACKCOUNTRY_SKI = "BackcountrySki"
    CANOEING = "Canoeing"
    CROSSFIT = "Crossfit"
    EBIKE_RIDE = "EBikeRide"
    ELLIPTICAL = "Elliptical"
    GOLF = "Golf"
    HANDCYCLE = "Handcycle"
    HIKE = "Hike"
    ICE_SKATE = "IceSkate"
    INLINE_SKATE = "InlineSkate"
    KAYAKING = "Kayaking"
    KITESURF = "Kitesurf"
    NORDIC_SKI = "NordicSki"
    RIDE = "Ride"
    ROCK_CLIMBING = "RockClimbing"
    ROLLER_SKI = "RollerSki"
    ROWING = "Rowing"
    RUN = "Run"
    SAIL = "Sail"
    SKATEBOARD = "Skateboard"
    SNOWBOARD = "Snowboard"
    SNOWSHOE = "Snowshoe"
    SOCCER = "Soccer"
    STAIR_STEPPER = "StairStepper"
    STAND_UP_PADDLING = "StandUpPaddling"
    SURFING = "Surfing"
    SWIM = "Swim"
    TRAIL_RUN = "TrailRun"
    VELOMOBILE = "Velomobile"
    VIRTUAL_RIDE = "VirtualRide"
    VIRTUAL_RUN = "VirtualRun"
    WALK = "Walk"
    WEIGHT_TRAINING = "WeightTraining"
    WHEELCHAIR = "Wheelchair"
    WINDSURF = "Windsurf"
    WORKOUT = "Workout"
    YOGA = "Yoga"

class SportType(str, Enum):
    CYCLING = "cycling"
    RUNNING = "running"
    SWIMMING = "swimming"
    OTHER = "other"

class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"

class TokenInfo(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int

# [Keep all other existing models...]

# Initialize MCP server
mcp = FastMCP("Strava")

# ==================== UTILITY FUNCTIONS ====================

def get_stored_token() -> Optional[TokenInfo]:
    """Get the stored auth token"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM auth_token ORDER BY created_at DESC LIMIT 1")
        token_row = cursor.fetchone()
        
        if not token_row:
            return None
        
        # Check if token is expired
        expires_at = token_row[3]
        if expires_at < datetime.now().timestamp() + 60:  # Add a 60-second buffer
            return None
        
        return TokenInfo(
            access_token=token_row[1],
            refresh_token=token_row[2],
            expires_at=token_row[3]
        )

def store_token(token: TokenInfo):
    """Store the auth token in the database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO auth_token (access_token, refresh_token, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token.access_token, token.refresh_token, token.expires_at, int(datetime.now().timestamp()))
        )
        conn.commit()

def refresh_strava_access_token(refresh_token: str) -> TokenInfo:
    """Refresh access token using the backend service"""
    try:
        response = requests.post(
            f"{TOKEN_SERVICE_URL}/refresh-token",
            json={'refresh_token': refresh_token},
            headers={'Content-Type': 'application/json'},
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.text}")
        
        data = response.json()
        return TokenInfo(
            access_token=data['access_token'],
            refresh_token=data['refresh_token'],
            expires_at=data['expires_at']
        )
        
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise Exception(f"Failed to refresh Strava token: {str(e)}")

def ensure_token() -> TokenInfo:
    """Ensure we have a valid token, refreshing if necessary"""
    # Try to get stored token
    token = get_stored_token()
    
    if not token:
        # Need to refresh token
        if not REFRESH_TOKEN:
            raise ValueError("No refresh token available. Please re-run the setup tool.")
        
        # Use backend service to refresh
        token = refresh_strava_access_token(REFRESH_TOKEN)
        store_token(token)
        logger.info("Refreshed Strava API token using backend service")
    
    return token

def format_seconds(seconds):
    """Format seconds to hours, minutes, seconds"""
    if not seconds:
        return None
        
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return f"{hours}h {minutes}m {seconds}s"

def strava_api_request(method, endpoint, access_token, params=None, data=None):
    """Make a request to the Strava API"""
    url = f"{STRAVA_API_BASE_URL}/{endpoint}"
    headers = {'Authorization': f'Bearer {access_token}'}
    
    try:
        if method.lower() == 'get':
            response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        elif method.lower() == 'post':
            response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        elif method.lower() == 'put':
            response = requests.put(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        elif method.lower() == 'delete':
            response = requests.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
            
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API request error: {e}")
        raise Exception(f"Strava API request failed: {str(e)}")

def format_activity_for_display(activity_data):
    """Format activity data for readable display"""
    # [Keep the existing format_activity_for_display function unchanged]
    formatted_data = {
        "id": activity_data.get("id"),
        "name": activity_data.get("name"),
        "type": activity_data.get("type"),
        "sport_type": activity_data.get("sport_type"),
        "start_date": activity_data.get("start_date"),
        "distance_km": activity_data.get("distance", 0) / 1000,
        "moving_time": format_seconds(activity_data.get("moving_time", 0)),
        "elapsed_time": format_seconds(activity_data.get("elapsed_time", 0)),
        "total_elevation_gain_m": activity_data.get("total_elevation_gain"),
        "average_speed_kph": (activity_data.get("average_speed", 0) * 3.6) if "average_speed" in activity_data else None,
        "max_speed_kph": (activity_data.get("max_speed", 0) * 3.6) if "max_speed" in activity_data else None,
        "average_heartrate": activity_data.get("average_heartrate"),
        "max_heartrate": activity_data.get("max_heartrate"),
        "kudos_count": activity_data.get("kudos_count"),
        "achievement_count": activity_data.get("achievement_count"),
        "pr_count": activity_data.get("pr_count"),
        "description": activity_data.get("description")
    }
    
    # Add gear info if available
    if "gear" in activity_data and activity_data["gear"]:
        formatted_data["gear"] = activity_data["gear"].get("name")
        formatted_data["gear_id"] = activity_data["gear"].get("id")
    
    # Add map data if available
    if "map" in activity_data and activity_data["map"]:
        map_data = activity_data["map"]
        formatted_data["map"] = {
            "id": map_data.get("id"),
            "polyline_available": bool(map_data.get("polyline") or map_data.get("summary_polyline"))
        }
    
    # Add splits if available
    if "splits_metric" in activity_data and activity_data["splits_metric"]:
        formatted_data["splits_km"] = activity_data["splits_metric"]
    
    # Add segment efforts if available but limit to count
    if "segment_efforts" in activity_data and activity_data["segment_efforts"]:
        formatted_data["segment_efforts_count"] = len(activity_data["segment_efforts"])
    
    # Remove None values
    formatted_data = {k: v for k, v in formatted_data.items() if v is not None}
    
    return json.dumps(formatted_data, indent=2)

# ==================== MCP TOOLS ====================

# [Keep all the existing MCP tools and resources unchanged - they use ensure_token() which now uses the backend service]

@mcp.tool()
def query_strava_database(
    sql: str,
    params: Optional[List[Any]] = None,
    limit: int = 300,
    offset: int = 0
) -> str:
    """
    Query the Strava database with flexible options including aggregation and grouping.
    
    [Keep the existing docstring and implementation]
    """
    # [Keep the existing implementation unchanged]
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Check if SQL is a SELECT query
            sql_lower = sql.strip().lower()
            if not sql_lower.startswith('select'):
                return "Error: Only SELECT queries are allowed"
                
            # [Rest of the implementation stays the same...]
            # Detect if the query already has a LIMIT clause
            has_limit = ' limit ' in sql_lower
            has_offset = ' offset ' in sql_lower
            
            # Add pagination if not already present
            modified_sql = sql
            if not has_limit:
                modified_sql += f" LIMIT {limit}"
            if not has_offset:
                modified_sql += f" OFFSET {offset}"
            
            # Execute the query
            if params:
                rows = cursor.execute(modified_sql, params).fetchall()
            else:
                rows = cursor.execute(modified_sql).fetchall()
                
            # [Keep rest of implementation the same...]
            # Format results and return pagination info
            results = []
            for row in rows:
                result = dict(row)
                # [Format results as before...]
                results.append(result)
            
            # Return data with pagination info
            response = {
                "results": results,
                "pagination": {
                    "total_matching_records": len(results),
                    "returned_records": len(results),
                    "limit": limit,
                    "offset": offset
                }
            }
            
            return json.dumps(response, indent=2)
            
    except Exception as e:
        logger.error(f"Error in query_strava_database: {e}")
        return f"Error querying database: {str(e)}"

# [Keep all other existing tools unchanged...]

@mcp.tool()
def get_activity_details(activity_id: str, fetch_from_api: bool = False) -> str:
    """Get detailed information about a specific activity."""
    # [Keep existing implementation - it uses ensure_token() which now uses backend service]
    pass

@mcp.tool()
def get_strava_stats() -> str:
    """Get summary statistics of stored Strava data"""
    # [Keep existing implementation unchanged]
    pass

@mcp.tool()
def get_gear_details(gear_id: Optional[str] = None) -> str:
    """Get detailed information about gear."""
    # [Keep existing implementation unchanged]
    pass

@mcp.tool()
def update_activity_from_strava(activity_id: str) -> str:
    """Update activity data from Strava API."""
    # [Keep existing implementation - uses ensure_token()]
    pass

@mcp.tool()
def get_athlete_zones() -> str:
    """Get the athlete's heart rate and power zones"""
    # [Keep existing implementation - uses ensure_token()]
    pass

# ==================== MCP RESOURCES ====================

# [Keep all existing resources unchanged]

@mcp.resource("strava://athlete")
def get_athlete_resource() -> str:
    """Get the athlete profile information"""
    # [Keep existing implementation]
    pass

# [Keep all other resources...]

# Run the server
if __name__ == "__main__":
    # Validate configuration
    if not REFRESH_TOKEN:
        logger.error("STRAVA_REFRESH_TOKEN environment variable must be set!")
        logger.error("Please re-run the setup tool: pipx run create-strava-mcp")
        exit(1)
    
    if not TOKEN_SERVICE_URL or TOKEN_SERVICE_URL == "https://your-strava-mcp-service.vercel.app":
        logger.error("STRAVA_TOKEN_SERVICE_URL environment variable must be set to your deployed service!")
        exit(1)
    
    logger.info(f"Starting Strava MCP server")
    logger.info(f"Token service: {TOKEN_SERVICE_URL}")
    logger.info(f"Database: {DB_PATH}")
    
    mcp.run()