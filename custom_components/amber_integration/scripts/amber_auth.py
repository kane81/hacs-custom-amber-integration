# =============================================================================
# Amber Authentication
# =============================================================================
# Authenticates with Amber via AWS Cognito and caches the IdToken, site ID
# and config ID to a local JSON file. Token is valid for 1 hour.
# amber_graphql.py calls this automatically when the token is expired.
#
# Usage:
#   python3 amber_auth.py
#   Called automatically by amber_graphql.py when token is expired.
#   Can also be called manually to force a token refresh.
#
# Output:
#   Writes token cache to /config/scripts/amber_token_cache.json
#
# Credentials:
#   Read from /config/secrets.yaml
#   amber_email:    your Amber app login email
#   amber_password: your Amber app login password
#
# How it works:
#   1. Reads email and password from secrets.yaml
#   2. Authenticates with Amber's AWS Cognito user pool using pycognito
#   3. Fetches your site ID and battery config ID from the Amber GraphQL API
#   4. Caches the IdToken, site ID and config ID to amber_token_cache.json
#   5. Token expires after 1 hour - amber_graphql.py auto-refreshes as needed
#
# Change Log:
#   v1.0    2026-03-27    Kane Li    - Initial version
# =============================================================================

import json
import sys
import re
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timezone, timedelta

# =============================================================================
# AMBER COGNITO CONFIGURATION
# These values are public infrastructure identifiers for Amber's AWS setup.
# They are the same for ALL Amber customers - not secrets, safe to share.
# Both can be found by inspecting the Amber mobile app network traffic.
# Do not change these unless Amber migrates their authentication infrastructure.
# =============================================================================

# Amber's AWS Cognito user pool - ap-southeast-2 = Sydney region
# Identifies the pool that holds all Amber customer accounts
COGNITO_POOL_ID   = "ap-southeast-2_vPQVymJLn"

# Amber's mobile app OAuth client ID
# Identifies the Amber app to Cognito - same value for every Amber customer
COGNITO_CLIENT_ID = "11naqf0mbruts1osrjsnl2ee1"

# Amber's GraphQL API endpoint
GRAPHQL_URL       = "https://backend.amber.com.au/graphql"

# Local cache file for token and site details
TOKEN_CACHE_PATH  = "/config/scripts/amber_token_cache.json"

# Path to HA secrets file
SECRETS_PATH      = "/config/secrets.yaml"

# =============================================================================


def load_secrets(secrets_path=SECRETS_PATH):
    """
    Reads credentials from HA secrets.yaml.
    Handles simple key: value pairs, ignores comments and blank lines.

    Args:
        secrets_path (str): Path to secrets.yaml

    Returns:
        dict: Parsed secrets key/value pairs
    """
    secrets = {}
    with open(secrets_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r'^(\w+)\s*:\s*(.+)$', line)
            if match:
                key   = match.group(1)
                value = match.group(2).strip().strip('"').strip("'")
                secrets[key] = value
    return secrets


def authenticate():
    """
    Authenticates with AWS Cognito using pycognito.
    Reads credentials from /config/secrets.yaml.

    Uses Amber's Cognito user pool with SRP (Secure Remote Password)
    authentication - pycognito handles the cryptographic challenge/response
    so we only need to provide email and password.

    Returns:
        str: IdToken JWT string valid for 1 hour
    """
    secrets  = load_secrets()
    email    = secrets.get("amber_email")
    password = secrets.get("amber_password")

    if not email:
        print("ERROR: amber_email not found in secrets.yaml")
        sys.exit(1)

    if not password:
        print("ERROR: amber_password not found in secrets.yaml")
        sys.exit(1)

    from pycognito import Cognito
    print(f"Authenticating as {email}...")
    u = Cognito(
        COGNITO_POOL_ID,
        COGNITO_CLIENT_ID,
        username=email
    )
    u.authenticate(password=password)
    print("Authentication successful")
    return u.id_token


def graphql(id_token, query, variables=None):
    """
    Makes a GraphQL request to the Amber backend.

    Args:
        id_token (str):   Cognito IdToken for authorisation
        query (str):      GraphQL query string
        variables (dict): GraphQL variables (optional)

    Returns:
        dict: Parsed GraphQL response data
    """
    ctx     = ssl.create_default_context()
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    req = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": id_token,
            "Content-Type":  "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, context=ctx) as resp:
        result = json.loads(resp.read())
        if "errors" in result:
            raise ValueError(f"GraphQL error: {result['errors']}")
        return result["data"]


def get_site_and_config(id_token):
    """
    Fetches the site ID and battery config ID from the Amber API.
    Both are required for battery override mutations.
    Discovered automatically at login - no need to hardcode them.

    Args:
        id_token (str): Cognito IdToken

    Returns:
        tuple: (site_id, config_id)
    """
    query = """
    query {
        smartshift {
            batterySetting {
                siteId
                selectedConfigId
            }
        }
    }
    """
    data      = graphql(id_token, query)
    battery   = data["smartshift"]["batterySetting"]
    site_id   = battery["siteId"]
    config_id = battery["selectedConfigId"]
    print(f"Site ID:   {site_id}")
    print(f"Config ID: {config_id}")
    return site_id, config_id


def save_token_cache(id_token, site_id, config_id):
    """
    Saves the token and site details to the cache file.
    Token expires in 1 hour - saves expiry time for auto-refresh check.

    Args:
        id_token (str):  Cognito IdToken
        site_id (str):   Amber site ID (your NMI site)
        config_id (str): Battery config ID (your battery registration)
    """
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache = {
        "id_token":   id_token,
        "site_id":    site_id,
        "config_id":  config_id,
        "expires_at": expires_at
    }
    with open(TOKEN_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"Token cached to {TOKEN_CACHE_PATH}")
    print(f"Expires at: {expires_at}")


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        id_token           = authenticate()
        site_id, config_id = get_site_and_config(id_token)
        save_token_cache(id_token, site_id, config_id)
        print("Auth complete - token cached successfully")
    except FileNotFoundError:
        print(f"ERROR: secrets.yaml not found at {SECRETS_PATH}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
