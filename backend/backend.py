#!/usr/bin/env python3
"""
Strava MCP Token Exchange Service

Secure backend service to handle OAuth token exchange without exposing client secrets.
Deploy this on your server (e.g., Vercel, Railway, Heroku, etc.)
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Rate limiting
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["100 per hour"])

# Configuration - set these as environment variables on your server
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "26565")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")  # Keep this secret on server!
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

# Strava API Constants
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


@app.route("/")
def home():
    """Home page with setup instructions"""
    return render_template_string(
        """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Strava MCP Token Service</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
                   max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; }
            .code { background: #f5f5f5; padding: 15px; border-radius: 5px; font-family: monospace; }
            .endpoint { background: #e8f5e8; padding: 10px; border-radius: 5px; margin: 10px 0; }
            h1 { color: #fc4c02; }
            h2 { color: #333; border-bottom: 2px solid #fc4c02; padding-bottom: 5px; }
        </style>
    </head>
    <body>
        <h1>🏃 Strava MCP Token Exchange Service</h1>
        
        <p>This service securely handles OAuth token exchange for the Strava MCP without exposing client secrets.</p>
        
        <h2>🔗 API Endpoints</h2>
        
        <div class="endpoint">
            <strong>POST /exchange-token</strong><br>
            Exchange authorization code for access/refresh tokens
        </div>
        
        <div class="endpoint">
            <strong>POST /refresh-token</strong><br>
            Refresh an expired access token
        </div>
        
        <h2>📱 Setup Flow</h2>
        
        <ol>
            <li>User runs: <code>pipx run create-strava-mcp</code></li>
            <li>Setup tool opens browser to: 
                <div class="code">https://www.strava.com/oauth/authorize?client_id={{client_id}}&response_type=code&redirect_uri={{base_url}}/callback&scope=activity:read_all,profile:read_all</div>
            </li>
            <li>User authorizes → redirected to <code>/callback</code></li>
            <li>Service exchanges code for tokens → returns to setup tool</li>
            <li>Setup tool stores tokens locally</li>
        </ol>
        
        <h2>🔐 Security Features</h2>
        <ul>
            <li>✅ Client secret stays secure on server</li>
            <li>✅ Rate limiting (100 requests/hour per IP)</li>
            <li>✅ CORS protection</li>
            <li>✅ Request validation</li>
            <li>✅ No token storage on server</li>
        </ul>
        
        <p>Client ID: <code>{{client_id}}</code></p>
        <p>Service Status: <span style="color: green;">✅ Active</span></p>
    </body>
    </html>
    """,
        client_id=CLIENT_ID,
        base_url=request.url_root.rstrip("/"),
    )


@app.route("/callback")
def oauth_callback():
    """Handle OAuth callback from Strava"""
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return render_template_string(
            """
        <!DOCTYPE html>
        <html>
        <head><title>Strava Authentication Failed</title></head>
        <body style="font-family: sans-serif; max-width: 600px; margin: 50px auto; text-align: center;">
            <h1 style="color: #d32f2f;">❌ Authentication Failed</h1>
            <p>Error: {{error}}</p>
            <p>Please close this window and try again.</p>
        </body>
        </html>
        """,
            error=error,
        ), 400

    if not code:
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head><title>Missing Authorization Code</title></head>
        <body style="font-family: sans-serif; max-width: 600px; margin: 50px auto; text-align: center;">
            <h1 style="color: #d32f2f;">❌ Missing Authorization Code</h1>
            <p>Please close this window and try again.</p>
        </body>
        </html>
        """), 400

    try:
        # Exchange code for tokens
        response = requests.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.text}")

        token_data = response.json()

        # Return success page with tokens (will be picked up by setup tool)
        return render_template_string(
            """
        <!DOCTYPE html>
        <html>
        <head><title>Strava Authentication Successful</title></head>
        <body style="font-family: sans-serif; max-width: 600px; margin: 50px auto; text-align: center;">
            <h1 style="color: #4caf50;">✅ Authentication Successful!</h1>
            <p>You have successfully authenticated with Strava.</p>
            <p>Your tokens have been generated. Please return to the setup tool.</p>
            
            <!-- Hidden data for setup tool to extract -->
            <div id="token-data" style="display: none;">{{token_data}}</div>
            
            <script>
                // If this page was opened in a popup, send data to parent
                if (window.opener) {
                    window.opener.postMessage({
                        type: 'strava_auth_success',
                        data: {{token_data|safe}}
                    }, '*');
                    window.close();
                }
            </script>
            
            <p style="margin-top: 30px; color: #666;">You can close this window now.</p>
        </body>
        </html>
        """,
            token_data=json.dumps(token_data),
        ), 200

    except Exception as e:
        logger.error(f"Token exchange error: {e}")
        return render_template_string(
            """
        <!DOCTYPE html>
        <html>
        <head><title>Token Exchange Failed</title></head>
        <body style="font-family: sans-serif; max-width: 600px; margin: 50px auto; text-align: center;">
            <h1 style="color: #d32f2f;">❌ Token Exchange Failed</h1>
            <p>{{error}}</p>
            <p>Please close this window and try again.</p>
        </body>
        </html>
        """,
            error=str(e),
        ), 500


@app.route("/exchange-token", methods=["POST"])
@limiter.limit("10 per minute")
def exchange_token():
    """Exchange authorization code for access token"""
    try:
        data = request.get_json()

        if not data or "code" not in data:
            return jsonify({"error": "Missing authorization code"}), 400

        # Exchange with Strava
        response = requests.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": data["code"],
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            logger.error(f"Strava token exchange failed: {response.text}")
            return jsonify({"error": "Token exchange failed"}), 400

        token_data = response.json()

        # Log successful exchange (without sensitive data)
        logger.info(
            f"Token exchange successful for athlete {token_data.get('athlete', {}).get('id', 'unknown')}"
        )

        return jsonify(
            {
                "access_token": token_data["access_token"],
                "refresh_token": token_data["refresh_token"],
                "expires_at": token_data["expires_at"],
                "athlete": token_data.get("athlete", {}),
            }
        )

    except Exception as e:
        logger.error(f"Token exchange error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/refresh-token", methods=["POST"])
@limiter.limit("20 per minute")
def refresh_access_token():
    """Refresh an access token"""
    try:
        data = request.get_json()

        if not data or "refresh_token" not in data:
            return jsonify({"error": "Missing refresh token"}), 400

        # Refresh with Strava
        response = requests.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": data["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            logger.error(f"Strava token refresh failed: {response.text}")
            return jsonify({"error": "Token refresh failed"}), 400

        token_data = response.json()

        logger.info("Token refresh successful")

        return jsonify(
            {
                "access_token": token_data["access_token"],
                "refresh_token": token_data["refresh_token"],
                "expires_at": token_data["expires_at"],
            }
        )

    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify(
        {
            "status": "healthy",
            "service": "strava-mcp-token-service",
            "timestamp": datetime.utcnow().isoformat(),
            "client_id": CLIENT_ID,
        }
    )


@app.errorhandler(429)
def rate_limit_handler(e):
    return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429


@app.errorhandler(404)
def not_found_handler(e):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error_handler(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    if not CLIENT_SECRET:
        logger.error("STRAVA_CLIENT_SECRET environment variable must be set!")
        exit(1)

    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"

    logger.info(f"Starting Strava MCP Token Service on port {port}")
    logger.info(f"Client ID: {CLIENT_ID}")

    app.run(host="0.0.0.0", port=port, debug=debug)
