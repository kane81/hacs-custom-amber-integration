# =============================================================================
# Amber GraphQL Client
# =============================================================================
# Reads the cached Amber auth token and calls the Amber GraphQL API to
# control Smart Shift and force battery discharge/charge.
#
# Key Features:
#   - Automatically refreshes expired auth token
#   - Polls live prices and updates HA helpers
#   - Controls battery override modes (charge / discharge / preserve)
#   - Ensures reliable override execution by cancelling existing overrides first
#
# Override Behaviour (IMPORTANT):
#   Amber API may ignore new overrides if one is already active (e.g. preserve).
#   To ensure deterministic behaviour, this script:
#
#       1. Cancels any active override
#       2. Waits 5 seconds (backend consistency delay)
#       3. Applies the requested override
#
# Usage:
#   python3 amber_graphql.py <command> [duration_minutes]
#
# Commands:
#   live                 - Poll live prices and metrics, update HA helpers
#   discharge <minutes>  - Force battery discharge for X minutes (default 60)
#   charge <minutes>     - Force battery charge for X minutes (default 60)
#   preserve <minutes>   - Force battery preserve for X minutes (default 60)
#   cancel               - Cancel any active battery override
#   smartshift_on        - Enable Smart Shift optimisation
#   smartshift_off       - Disable Smart Shift optimisation
#   status               - Show current battery status, SS state and live metrics
#
# Flags:
#   --enable-ss          - Auto re-enable Smart Shift if disabled before running
#                          discharge/charge/preserve. Without this flag the script
#                          exits with an error if Smart Shift is disabled.
#
# Examples:
#   python3 amber_graphql.py discharge 60
#   python3 amber_graphql.py discharge 60 --enable-ss
#   python3 amber_graphql.py status
#
# Change Log:
#   v1.0    2026-03-27    Kane Li  - Initial version
#   v1.1    2026-03-31    Kane Li  - Added cancel-before-override logic
#                                  - Added 5 second delay for reliability
#                                  - Prevents failures when battery is in preserve/manual mode
#   v1.2    2026-03-31    Kane Li  - Added Smart Shift status check before overrides
#                                  - discharge/charge/preserve exit with error if SS disabled
#                                  - --enable-ss flag auto re-enables SS before proceeding
#                                  - status command now shows Smart Shift enabled/disabled
#                                  - Fixed duplicate add_battery_override call in charge
#   v1.3    2026-04-01    Kane Li  - Fixed TypeError when liveMetrics is None
#                                  - Amber API occasionally returns null for liveMetrics
#                                  - between intervals; .get() default does not handle None
#                                  - Changed to `or {}` / `or 0` pattern to handle null
#   v1.4    2026-04-10    Kane Li  - Fixed same None TypeError in status command liveMetrics
#                                  - Added battery offline detection via stateOfChargePercentage
#                                  - None SOC = Amber cannot communicate with battery
#                                  - Writes amber_battery_offline boolean to HA
#                                  - Sends notification once on offline/online transition
#                                  - Added call_ha_service() helper function
#                                  - Updates binary_sensor.amber_battery_online in HA
# =============================================================================

import json
import sys
import subprocess
import urllib.request
import urllib.error
import ssl
import re
from datetime import datetime, timezone, timedelta
import time

TOKEN_CACHE_PATH = "/config/scripts/amber_token_cache.json"
GRAPHQL_URL      = "https://backend.amber.com.au/graphql"
SECRETS_PATH     = "/config/secrets.yaml"


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


def load_token_cache():
    """
    Loads the cached token from disk. If the token is expired or the cache
    file is missing, calls amber_auth.py to refresh it automatically.

    Returns:
        dict: Cache containing id_token, site_id, config_id, expires_at
    """
    try:
        with open(TOKEN_CACHE_PATH, "r") as f:
            cache = json.load(f)

        # Check if token is expired (with 5 minute buffer)
        expires_at = datetime.strptime(cache["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now        = datetime.now(timezone.utc)
        if now >= expires_at - timedelta(minutes=5):
            print("Token expired - refreshing...")
            refresh_token()
            with open(TOKEN_CACHE_PATH, "r") as f:
                cache = json.load(f)

        return cache

    except FileNotFoundError:
        print("No token cache found - running amber_auth.py...")
        refresh_token()
        with open(TOKEN_CACHE_PATH, "r") as f:
            return json.load(f)


def refresh_token():
    """
    Calls amber_auth.py to get a fresh token and update the cache.
    Exits with error if auth fails.
    """
    result = subprocess.run(
        ["python3", "/config/scripts/amber_auth.py"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"Auth failed: {result.stderr}")
        sys.exit(1)
    print(result.stdout)


def graphql(id_token, query, variables=None):
    """
    Makes a GraphQL request to the Amber backend.

    Args:
        id_token (str):   Cognito IdToken for authorisation
        query (str):      GraphQL query or mutation string
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


def update_ha_entity(ha_url, ha_token, entity_id, value, attributes=None):
    """
    Updates a HA entity state via the REST API.

    Args:
        ha_url (str):      Home Assistant base URL
        ha_token (str):    HA long-lived access token
        entity_id (str):   Entity ID to update
        value:             New state value
        attributes (dict): Optional attributes
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE

    payload = {"state": str(value)}
    if attributes:
        payload["attributes"] = attributes

    req = urllib.request.Request(
        f"{ha_url}/api/states/{entity_id}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {ha_token}",
            "Content-Type":  "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read())


def poll_live(id_token, site_id):
    """
    Polls the SmartShiftLive GraphQL query to get current prices and metrics.
    Updates all HA input_number helpers used by automations and dashboard.

    Price fields returned by SmartShiftLive:
      currentGeneralUsagePrice - buy price in cents, includes network fees
      currentFeedInPrice       - sell price in cents, includes tariff bonuses
                                 positive = receiving payment
                                 negative = paying to export

    SmartShiftLive does not expose the raw spot price separately. The sign
    of currentFeedInPrice matches the spot price sign, so it is used directly
    for amber_feed_in_spot_actual which drives the block_smart_shift automation.

    Args:
        id_token (str): Cognito IdToken
        site_id (str):  Amber site ID
    """
    query = """
    query SmartShiftLive($siteId: String) {
        smartshift {
            live(siteId: $siteId) {
                currentGeneralUsagePrice
                currentFeedInPrice
                stateOfChargePercentage
                liveMetrics {
                    ... on SmartShiftMetricsWithInterval {
                        importCostsCents
                        exportEarningsCents
                        totalEarningsCents
                    }
                }
            }
        }
    }
    """
    variables = {"siteId": site_id}
    data      = graphql(id_token, query, variables)
    live      = data["smartshift"]["live"]

    # Prices from SmartShiftLive are in cents - convert to $/kWh for HA helpers
    buy_price_cents  = live["currentGeneralUsagePrice"]
    sell_price_cents = live["currentFeedInPrice"]
    buy_price        = round(buy_price_cents / 100, 4)
    sell_price       = round(sell_price_cents / 100, 4)

    # Use effective sell price for spot - sign matches spot price direction
    feed_in_spot = sell_price

    # Battery SOC from Amber - updated every 5 minutes with the price poll
    # stateOfChargePercentage is None when Amber cannot communicate with the battery
    soc_raw      = live.get("stateOfChargePercentage")
    soc          = soc_raw if soc_raw is not None else 0
    battery_online = soc_raw is not None

    # Live metrics for current interval
    # Use `or {}` not `.get("liveMetrics", {})` — the API can return null for
    # liveMetrics between intervals, and .get() with a default does not handle
    # an explicit None value. `or {}` correctly falls back when None is returned.
    metrics               = live.get("liveMetrics") or {}
    import_cost_cents     = metrics.get("importCostsCents") or 0
    export_earnings_cents = metrics.get("exportEarningsCents") or 0
    total_earnings_cents  = metrics.get("totalEarningsCents") or 0

    print(f"Buy:    {buy_price_cents}c/kWh (${buy_price}/kWh)")
    print(f"Sell:   {sell_price_cents}c/kWh (${sell_price}/kWh)")
    print(f"SOC:    {soc}%")
    print(f"Import cost:     {import_cost_cents:.4f}c")
    print(f"Export earnings: {export_earnings_cents:.4f}c")
    print(f"Net:             {total_earnings_cents:.4f}c")

    # Load HA credentials from secrets
    secrets  = load_secrets()
    ha_url   = secrets.get("ha_url", "http://localhost:8123")
    ha_token = secrets.get("ha_long_lived_token")

    if not ha_token:
        print("ERROR: ha_long_lived_token not found in secrets.yaml")
        sys.exit(1)

    update_ha_entity(ha_url, ha_token,
        "input_number.amber_general_price_actual", buy_price,
        {"unit_of_measurement": "$/kWh", "friendly_name": "Amber General Price Actual"})

    update_ha_entity(ha_url, ha_token,
        "input_number.amber_feed_in_price_actual", sell_price,
        {"unit_of_measurement": "$/kWh", "friendly_name": "Amber Feed In Price Actual"})

    update_ha_entity(ha_url, ha_token,
        "input_number.amber_feed_in_spot_actual", feed_in_spot,
        {"unit_of_measurement": "$/kWh", "friendly_name": "Amber Feed In Spot Actual"})

    update_ha_entity(ha_url, ha_token,
        "input_number.amber_battery_soc", soc,
        {"unit_of_measurement": "%", "friendly_name": "Amber Battery SOC"})

    # Update battery online/offline state
    # on = Amber can communicate with battery, off = communication error
    update_ha_entity(ha_url, ha_token,
        "binary_sensor.amber_battery_online",
        "on" if battery_online else "off",
        {"friendly_name": "Amber Battery Online", "device_class": "connectivity"})

    update_ha_entity(ha_url, ha_token,
        "input_number.amber_import_cost_cents", round(import_cost_cents, 4),
        {"unit_of_measurement": "¢", "friendly_name": "Amber Import Cost Cents"})

    update_ha_entity(ha_url, ha_token,
        "input_number.amber_export_earnings_cents", round(export_earnings_cents, 4),
        {"unit_of_measurement": "¢", "friendly_name": "Amber Export Earnings Cents"})

    update_ha_entity(ha_url, ha_token,
        "input_number.amber_total_earnings_cents", round(total_earnings_cents, 4),
        {"unit_of_measurement": "¢", "friendly_name": "Amber Total Earnings Cents"})

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_ha_entity(ha_url, ha_token,
        "input_datetime.amber_last_polled", now_str,
        {"friendly_name": "Amber Last Polled"})

    print(f"HA updated. Last polled: {now_str}")


def add_battery_override(id_token, site_id, config_id, override_value, duration_minutes):
    """
    Forces the battery into a specific mode for a set duration via the
    Amber Smart Shift API. The API accepts any validFrom/validTo duration
    so there is no hard limit on how long the override can run.

    Args:
        id_token (str):         Cognito IdToken
        site_id (str):          Amber site ID
        config_id (str):        Battery config ID
        override_value (str):   One of: discharge, charge, preserve
        duration_minutes (int): How long to apply the override

    Returns:
        dict: Override details including overrideId and validTo
    """
    now        = datetime.now(timezone.utc)
    valid_from = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    valid_to   = (now + timedelta(minutes=duration_minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    mutation = """
    mutation SmartShiftAddBatteryOverride($input: AddBatteryOverrideInput!) {
        smartshift {
            addBatteryOverride(input: $input) {
                siteId
                configId
                overrideId
                value
                validFrom
                validTo
            }
        }
    }
    """
    variables = {
        "input": {
            "siteId":        site_id,
            "configId":      config_id,
            "overrideValue": override_value,
            "validFrom":     valid_from,
            "validTo":       valid_to
        }
    }
    data = graphql(id_token, mutation, variables)
    return data["smartshift"]["addBatteryOverride"]


def cancel_battery_override(id_token, site_id, config_id):
    """
    Cancels any active battery override.
    First fetches the active overrideId from status, then cancels it.

    Args:
        id_token (str):  Cognito IdToken
        site_id (str):   Amber site ID
        config_id (str): Battery config ID

    Returns:
        dict: Cancelled override details, or None if no active override
    """
    status   = get_status(id_token, site_id)
    override = status["batteryOverridesInfo"]["effectiveOverride"]

    if not override:
        print("No active override to cancel")
        return None

    override_id = override["overrideId"]
    print(f"Cancelling override: {override_id} ({override['value']})")

    mutation = """
    mutation SmartShiftCancelBatteryOverride($input: CancelBatteryOverrideInput!) {
        smartshift {
            cancelBatteryOverride(input: $input) {
                siteId
                configId
                overrideId
                value
                validFrom
                validTo
            }
        }
    }
    """
    variables = {
        "input": {
            "siteId":     site_id,
            "configId":   config_id,
            "overrideId": override_id
        }
    }
    data = graphql(id_token, mutation, variables)
    return data["smartshift"]["cancelBatteryOverride"]
    
def ensure_clean_override_state(id_token, site_id, config_id):
    """
    Ensures no conflicting override is active before applying a new one.

    Steps:
        1. Cancel any existing override
        2. Wait 5 seconds for backend consistency

    This prevents failures when the battery is manually set to preserve
    or another override is already active.
    """
    print("Ensuring clean state: cancelling any existing override...")
    cancel_battery_override(id_token, site_id, config_id)

    print("Waiting 5 seconds for backend to settle...")
    time.sleep(5)

def update_smartshift(id_token, config_id, enabled):
    """
    Enables or disables Smart Shift optimisation via the Amber API.
    Same as toggling the Smart Shift switch in the Amber app.

    Args:
        id_token (str):  Cognito IdToken
        config_id (str): Battery config ID
        enabled (bool):  True to enable, False to disable

    Returns:
        dict: Updated settings
    """
    mutation = """
    mutation UpdateSmartShiftDeviceSettings($input: UpdateSmartShiftDeviceSettingsInput!) {
        updateSmartShiftDeviceSettings(input: $input) {
            deviceId
            settings {
                optimisationEnabled
            }
        }
    }
    """
    variables = {
        "input": {
            "deviceId":            f"CONFIG#{config_id}",
            "optimisationEnabled": enabled
        }
    }
    data = graphql(id_token, mutation, variables)
    return data["updateSmartShiftDeviceSettings"]


def get_status(id_token, site_id):
    """
    Fetches live battery status, current interval metrics and any active
    battery override from the Amber Smart Shift API.

    Args:
        id_token (str): Cognito IdToken
        site_id (str):  Amber site ID

    Returns:
        dict: Live status including power state, SOC, metrics and override
    """
    query = """
    query SmartShiftStatus($siteId: String) {
        smartshift {
            live(siteId: $siteId) {
                batteryPowerW
                batteryEnergyWh
                batteryMaxEnergyWh
                stateOfChargePercentage
                powerState
                powerStateDescription
                currentGeneralUsagePrice
                currentFeedInPrice
                liveMetrics {
                    ... on SmartShiftMetricsWithInterval {
                        importCostsCents
                        exportEarningsCents
                        totalEarningsCents
                    }
                }
            }
            batteryOverridesInfo(siteId: $siteId) {
                effectiveOverride {
                    overrideId
                    value
                    validFrom
                    validTo
                    state
                }
            }
        }
        smartshiftBatteryStrategyConfig(siteId: $siteId) {
            configId
            status
        }
    }
    """
    variables = {"siteId": site_id}
    data      = graphql(id_token, query, variables)
    # Merge smartshiftBatteryStrategyConfig into returned dict for easy access
    result = data["smartshift"]
    result["smartshiftBatteryStrategyConfig"] = data.get("smartshiftBatteryStrategyConfig", {})
    return result


def get_ha_boolean(entity_id):
    """
    Reads a HA input_boolean state via the REST API.
    Returns True if the entity state is 'on', False otherwise.
    Returns None if the entity cannot be read.

    Args:
        entity_id (str): HA entity ID e.g. input_boolean.amber_block_smart_shift_active

    Returns:
        bool or None
    """
    try:
        secrets  = load_secrets()
        ha_url   = secrets.get("ha_url", "http://localhost:8123")
        ha_token = secrets.get("ha_long_lived_token")
        if not ha_token:
            return None

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE

        req = urllib.request.Request(
            f"{ha_url}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {ha_token}"}
        )
        with urllib.request.urlopen(req, context=ctx) as resp:
            data = json.loads(resp.read())
            return data.get("state") == "on"
    except Exception:
        return None


def check_smartshift_enabled(id_token, site_id, config_id, auto_enable=False):
    """
    Checks whether Smart Shift is currently enabled via the Amber API.

    Two scenarios when SS is disabled:
      1. amber_block_smart_shift_active = on  → disabled by OUR overnight automation
         → Always block, never auto-enable. The overnight block is intentional.
      2. amber_block_smart_shift_active = off → disabled externally (Amber app, manual)
         → Warn. If auto_enable=True, re-enable and proceed.

    Smart Shift must be enabled for battery overrides (discharge, charge, preserve)
    to take effect. Overrides sent while SS is disabled are silently ignored by Amber.

    Args:
        id_token (str):     Cognito IdToken
        site_id (str):      Amber site ID
        config_id (str):    Battery config ID
        auto_enable (bool): If True, re-enable SS if disabled externally

    Returns:
        bool: True if SS is enabled (or was successfully re-enabled), False otherwise
    """
    status    = get_status(id_token, site_id)
    ss_config = status.get("smartshiftBatteryStrategyConfig", {})
    ss_status = ss_config.get("status", "unknown")

    if ss_status == "enabled":
        print("Smart Shift is enabled - proceeding")
        return True

    print(f"WARNING: Smart Shift is currently disabled (status: {ss_status})")

    # Check if OUR overnight block automation disabled it
    block_active = get_ha_boolean("input_boolean.amber_block_smart_shift_active")

    if block_active:
        print("ERROR: Smart Shift was disabled by the amber_block_smart_shift overnight automation.")
        print("This is intentional — the overnight block is active.")
        print("Smart Shift will be re-enabled automatically when the overnight window ends.")
        print("Do not override this intentionally blocked state.")
        return False

    # SS is disabled but NOT by our automation — external source (Amber app, manual)
    print("Smart Shift appears to have been disabled externally (Amber app or manual toggle).")

    if auto_enable:
        print("Auto-enabling Smart Shift before proceeding...")
        update_smartshift(id_token, config_id, True)
        import time as _time
        _time.sleep(2)
        print("Smart Shift re-enabled - proceeding")
        return True
    else:
        print("ERROR: Cannot run override while Smart Shift is disabled.")
        print("To fix, run:  python3 amber_graphql.py smartshift_on")
        print("Or use the --enable-ss flag to auto-enable before running")
        return False


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python3 amber_graphql.py <command> [duration_minutes]")
        print("Commands: live, discharge, charge, preserve, cancel, smartshift_on, smartshift_off, status")
        sys.exit(1)

    command  = sys.argv[1].lower()
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    print(f"Command: {command}" + (f" ({duration} min)" if command in ["discharge", "charge", "preserve"] else ""))

    # Load cached token - auto refreshes if expired
    cache     = load_token_cache()
    id_token  = cache["id_token"]
    site_id   = cache["site_id"]
    config_id = cache["config_id"]

    print(f"Site ID:   {site_id}")
    print(f"Config ID: {config_id}")

    # Check if --enable-ss flag passed (auto re-enable SS if disabled)
    auto_enable_ss = "--enable-ss" in sys.argv

    if command == "live":
        poll_live(id_token, site_id)

    elif command == "discharge":
        if not check_smartshift_enabled(id_token, site_id, config_id, auto_enable=auto_enable_ss):
            sys.exit(1)
        ensure_clean_override_state(id_token, site_id, config_id)
        result = add_battery_override(id_token, site_id, config_id, "discharge", duration)
        print(f"Force discharge started!")
        print(f"Override ID: {result['overrideId']}")
        print(f"Valid from:  {result['validFrom']}")
        print(f"Valid to:    {result['validTo']}")

    elif command == "charge":
        if not check_smartshift_enabled(id_token, site_id, config_id, auto_enable=auto_enable_ss):
            sys.exit(1)
        ensure_clean_override_state(id_token, site_id, config_id)
        result = add_battery_override(id_token, site_id, config_id, "charge", duration)
        print(f"Force charge started!")
        print(f"Override ID: {result['overrideId']}")
        print(f"Valid from:  {result['validFrom']}")
        print(f"Valid to:    {result['validTo']}")

    elif command == "preserve":
        if not check_smartshift_enabled(id_token, site_id, config_id, auto_enable=auto_enable_ss):
            sys.exit(1)
        ensure_clean_override_state(id_token, site_id, config_id)
        result = add_battery_override(id_token, site_id, config_id, "preserve", duration)
        print(f"Force preserve started!")
        print(f"Override ID: {result['overrideId']}")
        print(f"Valid from:  {result['validFrom']}")
        print(f"Valid to:    {result['validTo']}")

    elif command == "cancel":
        result = cancel_battery_override(id_token, site_id, config_id)
        if result:
            print(f"Override cancelled!")
            print(f"Override ID:  {result['overrideId']}")
            print(f"Value:        {result['value']}")
            print(f"Was valid to: {result['validTo']}")
        else:
            print("No active override found - nothing to cancel")

    elif command == "smartshift_on":
        result = update_smartshift(id_token, config_id, True)
        print(f"Smart Shift enabled: {result['settings']['optimisationEnabled']}")

    elif command == "smartshift_off":
        result = update_smartshift(id_token, config_id, False)
        print(f"Smart Shift disabled: {result['settings']['optimisationEnabled']}")

    elif command == "status":
        status   = get_status(id_token, site_id)
        live     = status["live"]
        override = status["batteryOverridesInfo"]["effectiveOverride"]

        print(f"\n--- Battery Status ---")
        print(f"SOC:        {live['stateOfChargePercentage']}%")
        print(f"Power:      {live['batteryPowerW']}W")
        print(f"State:      {live['powerState']}")
        print(f"Buy price:  {live['currentGeneralUsagePrice']}c/kWh")
        print(f"Sell price: {live['currentFeedInPrice']}c/kWh")

        m = live.get("liveMetrics") or {}
        if m:
            print(f"\n--- Current Interval Metrics ---")
            print(f"Import cost:     ${(m.get('importCostsCents') or 0) / 100:.4f}")
            print(f"Export earnings: ${(m.get('exportEarningsCents') or 0) / 100:.4f}")
            print(f"Net:             ${(m.get('totalEarningsCents') or 0) / 100:.4f}")

        ss_config = status.get("smartshiftBatteryStrategyConfig", {})
        ss_status  = ss_config.get("status", "unknown")
        print(f"Smart Shift: {ss_status}")

        if override:
            print(f"\n--- Active Override ---")
            print(f"Mode:     {override['value']}")
            print(f"Valid to: {override['validTo']}")
            print(f"State:    {override['state']}")
        else:
            print(f"\nNo active override - Smart Shift in control")

    else:
        print(f"Unknown command: {command}")
        print("Commands: live, discharge, charge, preserve, cancel, smartshift_on, smartshift_off, status")
        sys.exit(1)
