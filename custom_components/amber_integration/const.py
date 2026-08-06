"""Constants for the Amber Electric Custom integration."""

import json
from pathlib import Path

DOMAIN = "amber_integration"

# -----------------------------------------------------------------------------
# Amber infrastructure identifiers
# These are public identifiers for Amber's AWS setup, the same for every Amber
# customer. Not secrets. Only change if Amber migrates their auth infrastructure.
# -----------------------------------------------------------------------------
COGNITO_POOL_ID = "ap-southeast-2_vPQVymJLn"
COGNITO_CLIENT_ID = "11naqf0mbruts1osrjsnl2ee1"
GRAPHQL_URL = "https://backend.amber.com.au/graphql"


def _get_manifest_version() -> str:
    """Reads the version straight from manifest.json, next to this file.

    manifest.json always ships alongside the integration's Python files at
    runtime, so this is safe here - unlike the standalone script, which gets
    copied to /config/scripts/ by install.sh and would have no manifest.json
    nearby to read (see the SCRIPT_VERSION comment in amber_graphql.py).
    """
    manifest_path = Path(__file__).parent / "manifest.json"
    try:
        with open(manifest_path) as f:
            return json.load(f).get("version", "unknown")
    except (OSError, json.JSONDecodeError):
        return "unknown"


# Self-identifying User-Agent sent on every direct call to Amber's GraphQL
# API. Without this, the underlying HTTP client's bare default is sent
# instead (e.g. "Python/3.x aiohttp/x.x") which doesn't identify the
# integration to Amber at all. Does not apply to the AWS Cognito auth
# handshake, which goes through pycognito/botocore rather than our own
# HTTP calls.
#
# Version comes from manifest.json so it can't drift out of sync with the
# actual installed version - bump manifest.json's "version" field and this
# updates automatically, no separate constant to remember to change.
USER_AGENT = f"HA-Kane-Cust-AmberV{_get_manifest_version()}"

# -----------------------------------------------------------------------------
# Config entry keys
# -----------------------------------------------------------------------------
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SITE_ID = "site_id"
CONF_CONFIG_ID = "config_id"
CONF_STATS_SCAN_INTERVAL = "stats_scan_interval"
CONF_PRICE_SCAN_INTERVAL = "price_scan_interval"

# Two independent poll intervals, because the two things they fetch change
# at very different rates. Amber's own PRICES only update every 5 minutes
# regardless of how often this is polled - polling faster just gets you the
# same price repeated. Battery telemetry (SOC, battery power, powerState,
# override status) is much closer to real-time, which is why it has its own
# faster schedule. Splitting the underlying query in two (see api.py) means
# fast telemetry polling doesn't waste calls re-fetching unchanged prices.

DEFAULT_STATS_SCAN_INTERVAL = 30  # seconds
MIN_STATS_SCAN_INTERVAL = 15
MAX_STATS_SCAN_INTERVAL = 1800

DEFAULT_PRICE_SCAN_INTERVAL = 330  # 5 minutes 30 seconds
MIN_PRICE_SCAN_INTERVAL = 30
MAX_PRICE_SCAN_INTERVAL = 1800

# Price polling is aligned to the wall clock rather than run on a plain
# repeating timer: Amber publishes prices on 5-minute market boundaries, so
# polls happen at :00:30, :05:30, :10:30 and so on. A drifting interval could
# settle just before a boundary and consistently read the previous interval's
# price. The 30s offset is because Amber's publish isn't instant on the
# boundary - asking exactly on the minute can still return the old value.
#
# Only applies while the interval is left at the default. Choosing a custom
# Market Price Poll Interval switches back to a plain repeating timer.
PRICE_POLL_BLOCK_MINUTES = 5
PRICE_POLL_OFFSET_SECONDS = 30

# -----------------------------------------------------------------------------
# Battery override values accepted by the Amber API
#
# All four confirmed against captured Amber app network traces - these are the
# exact strings the app itself sends. Note the ones that aren't the obvious
# guess: "preserve-charge" not "preserve", and "self-consume" not "consume".
# Both were originally wrong here and rejected by the API until traced.
# -----------------------------------------------------------------------------
OVERRIDE_CHARGE = "charge"
OVERRIDE_DISCHARGE = "discharge"
OVERRIDE_PRESERVE = "preserve-charge"
OVERRIDE_CONSUME = "self-consume"

DEFAULT_OVERRIDE_DURATION = 60  # minutes

# Skip the cancel/reapply cycle if the same override already has at least this
# many minutes left, so re-applying an already-running override is a no-op
# rather than a needless cancel + 5s settle + re-apply round trip.
OVERRIDE_CONTINUITY_MINUTES = 7

# Seconds to wait after cancelling before applying a new override, so the Amber
# backend reaches a consistent state.
OVERRIDE_SETTLE_SECONDS = 5

# Seconds to wait after enabling Smart Shift before sending an override.
# Amber silently ignores overrides while Smart Shift is off - it accepts the
# call and returns success but does nothing - so if this wait is too short
# the override is lost with no error to indicate it. Was previously a bare
# 2, inconsistent with OVERRIDE_SETTLE_SECONDS above despite being the same
# kind of backend propagation wait; matched to 5 since the failure mode here
# (override silently dropped) is worse than waiting a few extra seconds.
SMARTSHIFT_ENABLE_SETTLE_SECONDS = 5

# -----------------------------------------------------------------------------
# Services
# -----------------------------------------------------------------------------
SERVICE_FORCE_CHARGE = "force_charge"
SERVICE_FORCE_DISCHARGE = "force_discharge"
SERVICE_PRESERVE_CHARGE = "preserve_charge"
SERVICE_CONSUME = "consume"
SERVICE_CANCEL_OVERRIDE = "cancel_override"
SERVICE_SMARTSHIFT_ON = "smartshift_on"
SERVICE_SMARTSHIFT_OFF = "smartshift_off"
SERVICE_REFRESH = "refresh"

ATTR_DURATION = "duration"
# Optional field on the override services identifying the caller ("manual",
# "auto_buy", "auto_sell", ...), so a later poll can report who currently
# owns the active override. Not an access control mechanism - purely
# bookkeeping so the automation blueprints can tell whether an override is
# one they applied themselves before deciding whether to cancel it. Defaults
# to "service" for callers that don't specify it.
ATTR_SOURCE = "source"

# The five Power sensor entity_id fields - shared between config_flow.py
# (which offers to seed them during setup) and text.py (which defines the
# entities themselves and reads that seed as their initial value). Keeping
# these as one set of constants rather than matching string literals in
# both files means a rename can't accidentally desync them.
CONF_POWER_BATTERY_SENSOR = "power_battery_sensor"
CONF_POWER_BATTERY_LEVEL_SENSOR = "power_battery_level_sensor"
CONF_POWER_SOLAR_SENSOR = "power_solar_sensor"
CONF_POWER_LOAD_SENSOR = "power_load_sensor"
CONF_POWER_GRID_SENSOR = "power_grid_sensor"

# -----------------------------------------------------------------------------
# Automation settings (Part 2)
#
# These configure the optional automation suite. They live in Part 1 so the
# automations can ship as blueprints - a blueprint cannot create helpers, and
# these have to exist before an automation can reference them.
#
# On a Part-1-only install they do nothing. They're marked EntityCategory.CONFIG
# so they sit in the collapsed Configuration section of the device page rather
# than cluttering the main controls.
#
# Not persisted across restarts by the integration itself - HA's own state
# restoration handles that (RestoreEntity), so a restart keeps your settings.
# -----------------------------------------------------------------------------

# Auto Sell / Auto Buy - three independent rules per direction, no time
# windows. Each rule is a battery-level condition plus a price threshold,
# with its own on/off. Which rule applies at any moment is worked out from
# the battery level itself, not from which slot (Rule 1/2/3) the user put it
# in - the enabled+satisfied rule with the most specific (for Sell: highest,
# for Buy: lowest) battery threshold wins. That makes the three rules
# genuinely order-independent: swap Rule 1 and Rule 3's numbers around and
# the resulting behaviour is identical, because it's a value comparison, not
# a "check Rule 1 first" sequence.
#
# Defaults below are just a sensible out-of-the-box starting point, in the
# order most people would think of them - they don't encode any required
# ordering, since none exists.

# Auto Sell - the more charge you're sitting on, the less you need to be
# paid to give some up, so the fullest tier accepts the lowest price.
DEFAULT_SELL_RULE_1_BATTERY = 80    # %
DEFAULT_SELL_RULE_1_PRICE = 0.15    # $/kWh
DEFAULT_SELL_RULE_2_BATTERY = 50
DEFAULT_SELL_RULE_2_PRICE = 0.20
DEFAULT_SELL_RULE_3_BATTERY = 0
DEFAULT_SELL_RULE_3_PRICE = 0.80

# Auto Buy - the emptier the battery, the more urgent the need, so the
# emptiest tier accepts paying the most.
DEFAULT_BUY_RULE_1_BATTERY = 30     # %
DEFAULT_BUY_RULE_1_PRICE = 0.15     # $/kWh
DEFAULT_BUY_RULE_2_BATTERY = 60
DEFAULT_BUY_RULE_2_PRICE = 0.07
DEFAULT_BUY_RULE_3_BATTERY = 90
DEFAULT_BUY_RULE_3_PRICE = 0.01

# Price bounds for the threshold entities. Both cap at $30/kWh, covering
# genuine NEM price spikes. The asymmetry is at the floor: selling below $0
# makes no sense (that's paying to export), but buying can go negative
# during oversupply events, when the grid pays you to consume.
MIN_SELL_PRICE_BOUND = 0.0
MAX_SELL_PRICE_BOUND = 30.0
MIN_BUY_PRICE_BOUND = -5.0
MAX_BUY_PRICE_BOUND = 30.0
