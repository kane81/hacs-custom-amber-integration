#!/usr/bin/env python3
# =============================================================================
# amber_graphql.py - Standalone Amber Smart Shift API tool
# =============================================================================
#
# A developer/debugging tool for making ad-hoc calls against Amber's private
# Smart Shift API - the same one this project's Home Assistant integration
# uses, but callable directly from a terminal without going through HA at
# all. Not part of Part 1 or Part 2 - nothing in this project depends on
# this script; it exists purely for exploring the API and testing things by
# hand.
#
# Every query and mutation in the commands below is either copied directly
# from custom_components/amber_integration/api.py (the same code your
# actual installed integration runs), or confirmed against a captured
# request/response from the Amber app's own network traffic - see the
# comment above each query for exactly which and where it came from. None
# of it is guessed.
#
# -----------------------------------------------------------------------------
# Setup
#
# Needs pycognito (same dependency the integration uses):
#   pip install pycognito --break-system-packages
#
# Credentials come from environment variables, not a config file or
# command-line argument, so they don't end up in your shell history or a
# process list:
#   export AMBER_EMAIL="you@example.com"
#   export AMBER_PASSWORD="your amber app password"
#
# -----------------------------------------------------------------------------
# Usage:
#   python3 amber_graphql.py <command> [args]
#
# Commands:
#   live                        - Current buy/sell price, battery %, power,
#                                  active override, Smart Shift state, and
#                                  this interval's import/export/net cost.
#   live-detail                 - Full live power-flow snapshot: solar, house
#                                  load, battery and grid import/export, plus
#                                  battery % and current prices. Richer than
#                                  "live" - which only covers battery/price -
#                                  but a separate query, so it costs an extra
#                                  API call rather than replacing "live".
#   status                      - Shorter version of live - just the battery,
#                                  Smart Shift and override state, no prices.
#   usage [days]                - Daily import/export usage and cost for the
#                                  current billing period (default: last 7
#                                  days). Same data as the app's Usage tab.
#   prices                      - Current buy/sell price (from the live 5-min
#                                  window), a short 5-min forecast, a
#                                  day-ahead 30-min forecast, and recent
#                                  30-min history. Same data as the app's
#                                  Live Prices tab.
#   plan [past] [forecast]      - Everything live-detail has, plus Amber's
#                                  own forecast and the reasoning behind
#                                  recent/upcoming battery actions (default:
#                                  6 past, 6 forecast 5-min periods). Same
#                                  data as the app's Plan tab.
#   discharge <minutes>         - Force battery discharge (default 60 min)
#   charge <minutes>            - Force battery charge (default 60 min)
#   preserve-charge <minutes>   - Force battery to hold its current charge
#   consume <minutes>           - Force plain self-consumption (solar charges
#                                  it, house load discharges it)
#   cancel                      - Cancel whatever override is currently active
#   smartshift_on                - Enable Smart Shift optimisation
#   smartshift_off               - Disable Smart Shift optimisation
#
# All four override commands auto-enable Smart Shift first if it's off -
# Amber silently ignores an override applied while Smart Shift is disabled,
# so this avoids the override quietly doing nothing. Matches the
# integration's own behaviour exactly (see api.py's async_set_override).
#
# Examples:
#   python3 amber_graphql.py live
#   python3 amber_graphql.py live-detail
#   python3 amber_graphql.py plan
#   python3 amber_graphql.py plan 12 24
#   python3 amber_graphql.py usage 14
#   python3 amber_graphql.py discharge 30
#   python3 amber_graphql.py status
#
# =============================================================================

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

COGNITO_POOL_ID = "ap-southeast-2_vPQVymJLn"
COGNITO_CLIENT_ID = "11naqf0mbruts1osrjsnl2ee1"
GRAPHQL_URL = "https://backend.amber.com.au/graphql"
USER_AGENT = "HA-Kane-Cust-AmberV-cli"

SMARTSHIFT_ENABLE_SETTLE_SECONDS = 5
OVERRIDE_SETTLE_SECONDS = 5

# -----------------------------------------------------------------------------
# Queries - copied directly from api.py, unchanged. If the integration's
# queries ever change, these will drift out of sync with it; check api.py
# first if a command here starts behaving differently than the integration.
# -----------------------------------------------------------------------------

SITE_QUERY = """
query { smartshift { batterySetting { siteId selectedConfigId } } }
"""

STATS_QUERY = """
query SmartShiftStats($siteId: String) {
    smartshift {
        live(siteId: $siteId) {
            stateOfChargePercentage
            batteryPowerW
            powerState
            powerStateDescription
        }
        batteryOverridesInfo(siteId: $siteId) {
            effectiveOverride { overrideId value validFrom validTo state estimatedEndDate }
        }
    }
    smartshiftBatteryStrategyConfig(siteId: $siteId) { configId status }
}
"""

PRICE_QUERY = """
query SmartShiftPrices($siteId: String) {
    smartshift {
        live(siteId: $siteId) {
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
    }
}
"""

ADD_OVERRIDE = """
mutation SmartShiftAddBatteryOverride($input: AddBatteryOverrideInput!) {
    smartshift {
        addBatteryOverride(input: $input) {
            overrideId value validFrom validTo
        }
    }
}
"""

CANCEL_OVERRIDE = """
mutation SmartShiftCancelBatteryOverride($input: CancelBatteryOverrideInput!) {
    smartshift {
        cancelBatteryOverride(input: $input) { overrideId value }
    }
}
"""

SET_SMARTSHIFT = """
mutation UpdateSmartShiftDeviceSettings($input: UpdateSmartShiftDeviceSettingsInput!) {
    updateSmartShiftDeviceSettings(input: $input) {
        deviceId
        settings { optimisationEnabled }
    }
}
"""

# -----------------------------------------------------------------------------
# Usage tab - daily billing/usage stats
#
# A separate query namespace from smartshift - operation name "Snapshots",
# not nested under smartshift at all. Confirmed by capturing the app's
# Usage tab request/response.
#
# billingDays is a union of three day types:
#   MissingBillingDay   - only marketDate, no data available for that day
#   CompleteBillingDay  - full data, same field set as EstimatedBillingDay
#   EstimatedBillingDay - full data but not yet finalised by the market
# Both Complete and Estimated carry a usageSummaries block with general
# (grid import), feedIn (export) and controlled (a separate controlled-load
# circuit, null on accounts without one) breakdowns.
#
# Costs/earnings are in cents. usageKwh/suppliedKwh are in kWh.
# -----------------------------------------------------------------------------

USAGE_QUERY = """
query SmartShiftUsageCli($siteId: String, $weekLimit: Int!, $weekOffset: Int) {
    snapshots(siteId: $siteId, weekLimit: $weekLimit, weekOffset: $weekOffset) {
        periodSummary {
            costInCents
            usageKwh
            renewablePercentage
            usageType
        }
        billingDays {
            __typename
            ... on MissingBillingDay {
                marketDate
            }
            ... on CompleteBillingDay {
                marketDate
                usageSummaries {
                    general { usageKwh costInCents renewablePercentage }
                    feedIn { suppliedKwh earningsInCents }
                    controlled { usageKwh costInCents }
                    combined { costInCents renewablePercentage }
                }
            }
            ... on EstimatedBillingDay {
                marketDate
                usageSummaries {
                    general { usageKwh costInCents renewablePercentage }
                    feedIn { suppliedKwh earningsInCents }
                    controlled { usageKwh costInCents }
                    combined { costInCents renewablePercentage }
                }
            }
        }
    }
}
"""

# -----------------------------------------------------------------------------
# Live prices tab
#
# The operation is named "Home" (it's the app's home screen query) but
# sitePricing is the piece that renders the Live Prices tab; the rest of
# that query is unrelated to pricing and is not requested here.
#
# sitePricing has two resolutions:
#   meterWindows          30-minute periods - the day-ahead view.
#   fiveMinMeterWindows    5-minute periods. currentPeriod here is the live
#                          one (estimate=false), fresher than the 30-minute
#                          window's own currentPeriod (estimate=true).
#
# Each resolution carries GENERAL (buy/import) and FEED_IN (sell/export)
# usageType windows.
# -----------------------------------------------------------------------------

PRICE_PERIOD_FIELDS = """
                    start
                    kwhPriceInCents
                    mlKwhPriceInCents
                    renewablePercentage
                    indicator
                    indicatorAgainstDmo
                    demandWindow
                    estimate
"""

PRICES_QUERY = f"""
query SmartShiftPricesCli($siteId: String) {{
    sitePricing(siteId: $siteId) {{
        generalRemark
        solarRemark
        spikeRemark
        meterWindows {{
            usageType
            currentPeriod {{ {PRICE_PERIOD_FIELDS} }}
            previousPeriods {{ {PRICE_PERIOD_FIELDS} }}
            forecastPeriods {{ {PRICE_PERIOD_FIELDS} }}
        }}
        fiveMinMeterWindows {{
            usageType
            currentPeriod {{ {PRICE_PERIOD_FIELDS} }}
            forecastPeriods {{ {PRICE_PERIOD_FIELDS} }}
        }}
    }}
}}
"""


# -----------------------------------------------------------------------------
# Auth + transport
# -----------------------------------------------------------------------------

def cognito_login(email: str, password: str) -> str:
    """Blocking Cognito login - returns the id_token."""
    from pycognito import Cognito

    cognito = Cognito(COGNITO_POOL_ID, COGNITO_CLIENT_ID, username=email)
    cognito.authenticate(password=password)
    return cognito.id_token


def graphql(id_token: str, query: str, variables: dict | None = None) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables

    req = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": id_token,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR: HTTP {e.code} from Amber - {e.read().decode('utf-8', 'replace')}")
        sys.exit(1)

    if "errors" in body:
        messages = "; ".join(err.get("message", "") for err in body["errors"])
        print(f"ERROR: Amber API returned an error - {messages}")
        sys.exit(1)

    return body["data"]


def discover_site(id_token: str) -> tuple[str, str]:
    data = graphql(id_token, SITE_QUERY)
    setting = data["smartshift"]["batterySetting"]
    return setting["siteId"], setting["selectedConfigId"]


# -----------------------------------------------------------------------------
# Reads
# -----------------------------------------------------------------------------

def get_stats(id_token: str, site_id: str) -> dict:
    data = graphql(id_token, STATS_QUERY, {"siteId": site_id})
    ss = data.get("smartshift") or {}
    live = ss.get("live") or {}
    override = (ss.get("batteryOverridesInfo") or {}).get("effectiveOverride")
    strategy = data.get("smartshiftBatteryStrategyConfig") or {}
    return {
        "soc": live.get("stateOfChargePercentage"),
        "battery_power_w": live.get("batteryPowerW"),
        "power_state": live.get("powerState"),
        "power_state_description": live.get("powerStateDescription"),
        "override": override,
        "smartshift_enabled": strategy.get("status") == "enabled",
    }


def get_live_prices(id_token: str, site_id: str) -> dict:
    data = graphql(id_token, PRICE_QUERY, {"siteId": site_id})
    live = (data.get("smartshift") or {}).get("live") or {}
    metrics = live.get("liveMetrics") or {}
    return {
        "buy_cents": live.get("currentGeneralUsagePrice"),
        "sell_cents": live.get("currentFeedInPrice"),
        "import_cost_cents": metrics.get("importCostsCents"),
        "export_earnings_cents": metrics.get("exportEarningsCents"),
        "net_earnings_cents": metrics.get("totalEarningsCents"),
    }


def get_usage(id_token: str, site_id: str, week_limit: int = 4, week_offset: int = 0) -> dict:
    """
    Fetches daily import/export usage and cost for the current billing period.

    Returns:
        dict: {
            "period_summary": {...combined usage for the whole period...} | None,
            "days": [
                {
                    "date": "2026-07-30",
                    "status": "complete" | "estimated" | "missing",
                    "import_kwh": float, "import_cost_cents": float,
                    "export_kwh": float, "export_earnings_cents": float,
                    "controlled_kwh": float | None, "controlled_cost_cents": float | None,
                    "net_cost_cents": float, "renewable_percentage": float,
                }, ...
            ],  # oldest first, matching the API's own order
        }
    """
    variables = {"siteId": site_id, "weekLimit": week_limit, "weekOffset": week_offset}
    data = graphql(id_token, USAGE_QUERY, variables)
    snap = data["snapshots"]

    days = []
    for day in snap.get("billingDays") or []:
        typename = day.get("__typename")
        if typename == "MissingBillingDay":
            days.append({
                "date": day["marketDate"], "status": "missing",
                "import_kwh": None, "import_cost_cents": None,
                "export_kwh": None, "export_earnings_cents": None,
                "controlled_kwh": None, "controlled_cost_cents": None,
                "net_cost_cents": None, "renewable_percentage": None,
            })
            continue

        summaries = day.get("usageSummaries") or {}
        general = summaries.get("general") or {}
        feed_in = summaries.get("feedIn") or {}
        controlled = summaries.get("controlled")
        combined = summaries.get("combined") or {}

        days.append({
            "date": day["marketDate"],
            "status": "complete" if typename == "CompleteBillingDay" else "estimated",
            "import_kwh": general.get("usageKwh"),
            "import_cost_cents": general.get("costInCents"),
            "export_kwh": feed_in.get("suppliedKwh"),
            "export_earnings_cents": feed_in.get("earningsInCents"),
            "controlled_kwh": controlled.get("usageKwh") if controlled else None,
            "controlled_cost_cents": controlled.get("costInCents") if controlled else None,
            "net_cost_cents": combined.get("costInCents"),
            "renewable_percentage": combined.get("renewablePercentage"),
        })

    return {"period_summary": snap.get("periodSummary"), "days": days}


def get_prices(id_token: str, site_id: str, prev_count: int = 6, forecast_count: int = 6,
                five_min_forecast_count: int = 7) -> dict:
    """
    Fetches the current price plus recent history and forecast, for both
    general usage (buy) and feed-in (sell).
    """
    data = graphql(id_token, PRICES_QUERY, {"siteId": site_id})
    sp = data["sitePricing"]

    def by_type(windows, usage_type):
        return next((w for w in windows if w["usageType"] == usage_type), {})

    result = {
        "remarks": {
            "general": sp.get("generalRemark"),
            "solar": sp.get("solarRemark"),
            "spike": sp.get("spikeRemark"),
        }
    }

    for key, usage_type in (("general", "GENERAL"), ("feed_in", "FEED_IN")):
        mw = by_type(sp["meterWindows"], usage_type)
        five = by_type(sp["fiveMinMeterWindows"], usage_type)
        result[key] = {
            "current": five.get("currentPeriod") or mw.get("currentPeriod"),
            "previous": (mw.get("previousPeriods") or [])[-prev_count:][::-1],
            "forecast": (mw.get("forecastPeriods") or [])[:forecast_count],
            "forecast_5min": (five.get("forecastPeriods") or [])[:five_min_forecast_count],
        }

    return result


# -----------------------------------------------------------------------------
# Live power flow + Plan tab
#
# Both confirmed by capturing the app's Plan tab request/response directly
# (operation "SmartShiftPlan"). The captured query also requested settings,
# smartshiftExperience, systemHealth, dataConnection and sitePricing.meterWindows
# - all UI/diagnostic concerns unrelated to what this tool is for, so they're
# deliberately left out here. Trimming them meant also dropping the
# $showSolarPrice variable, since it was only used by the dropped
# sitePricing field - keeping it declared but unused would be exactly the
# "variable is never used" validation error usage hit before this.
#
# smartshift.plan() turns out to be the answer to "solar/house/grid power
# flow" that the STATS_QUERY behind `live`/`status` never had - it returns
# sitePowerW (net grid import/export - negative sitePowerW lined up with
# battery discharge minus house load plus solar in the captured response,
# confirming the sign: negative = exporting), solarPowerW, fixedLoadPowerW
# (house load) and batteryPowerW all in one place, alongside the existing
# battery/price fields STATS_QUERY and PRICE_QUERY already cover separately.
#
# actionDescriptions is a bare scalar field (no sub-selection) in the
# confirmed request - it returns a JSON object as a single opaque value,
# not a GraphQL object type, so it must NOT be given `{ }` sub-fields or
# the server will reject the query.
#
# actionDecisions is a union: SmartShiftBatteryActionDecision (confirmed
# populated in the capture, values seen: "discharge", "preserve-charge")
# and SmartShiftSolarActionDecision (present in the confirmed request's
# field selection, so the query itself is valid, but never actually
# populated in the captured response - this account's solar wasn't under
# automated control during the capture window). Parsing handles it
# defensively either way rather than assuming it's populated.
#
# duringControlSummary is also a union (one variant per override type:
# charge/discharge/preserve/self-consume) but was null throughout the
# capture, since no override was active at the time - requested here since
# the query itself is confirmed valid, but not parsed into named fields
# since there's no confirmed example of its populated shape. Shown as raw
# JSON if present rather than guessed at.
# -----------------------------------------------------------------------------

LIVE_DETAIL_QUERY = """
query SmartShiftLiveDetailCli($siteId: String, $env: String) {
    smartshift {
        plan(siteId: $siteId, env: $env) {
            sitePowerW
            solarPowerW
            fixedLoadPowerW
            batteryPowerW
            batteryEnergyWh
            batteryMaxEnergyWh
            powerState
            powerStateDescription
            powerStateAction
            powerStateActionTitle
            powerStateActionDescription
            stateOfChargePercentage
            currentGeneralUsagePrice
            currentFeedInPrice
            currentRenewablePercentage
        }
    }
}
"""


def get_live_detail(id_token: str, site_id: str, env: str = "prod") -> dict:
    """Fetches a full live power-flow snapshot: solar, house load, battery
    and grid import/export, alongside battery % and current prices - a
    richer view than `live`/`status`, which only cover battery and price."""
    data = graphql(id_token, LIVE_DETAIL_QUERY, {"siteId": site_id, "env": env})
    return data["smartshift"]["plan"]


PLAN_QUERY = """
query SmartShiftPlanCli($siteId: String, $env: String) {
    smartshift {
        plan(siteId: $siteId, env: $env) {
            sitePowerW
            solarPowerW
            fixedLoadPowerW
            batteryPowerW
            batteryEnergyWh
            batteryMaxEnergyWh
            powerState
            powerStateDescription
            stateOfChargePercentage
            currentGeneralUsagePrice
            currentFeedInPrice
            currentRenewablePercentage
            forecastData {
                __typename
                ... on PastAndForecastData {
                    past {
                        periodStart
                        periodEnd
                        generalUsagePriceCents
                        feedInPriceCents
                        batteryEnergyWh
                        solarPowerW
                        fixedLoadPowerW
                        actionDescriptions
                        actionDecisions {
                            __typename
                            ... on SmartShiftBatteryActionDecision {
                                entityId
                                batteryAction: action
                                reason
                            }
                            ... on SmartShiftSolarActionDecision {
                                entityId
                                solarAction: action
                                reason
                            }
                        }
                    }
                    forecast {
                        periodStart
                        periodEnd
                        generalUsagePriceCents
                        feedInPriceCents
                        batteryEnergyWh
                        solarPowerW
                        fixedLoadPowerW
                        actionDescriptions
                        actionDecisions {
                            __typename
                            ... on SmartShiftBatteryActionDecision {
                                entityId
                                batteryAction: action
                                reason
                            }
                            ... on SmartShiftSolarActionDecision {
                                entityId
                                solarAction: action
                                reason
                            }
                        }
                    }
                    forecastError {
                        type
                        title
                        message
                    }
                }
                ... on SmartShiftDataError {
                    type
                    title
                    message
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
                estimatedStartDate
                estimatedEndDate
                isEvOverride
            }
            duringControlSummary
        }
    }
}
"""


def get_plan(id_token: str, site_id: str, env: str = "prod", past_count: int = 6,
             forecast_count: int = 12) -> dict:
    """Fetches the live power-flow snapshot plus Amber's own forecast and
    the reasoning behind recent/upcoming battery actions - the data behind
    the app's Plan tab.

    Returns:
        dict: {
            **live_detail fields (sitePowerW, solarPowerW, etc)**,
            "override": {...effectiveOverride...} | None,
            "during_control_summary": <raw dict> | None,  # union type, not
                                                            # confirmed populated
            "past": [...5-min periods, most recent first...],
            "forecast": [...5-min periods, soonest first...],
            "forecast_error": {...} | None,
        }
    """
    data = graphql(id_token, PLAN_QUERY, {"siteId": site_id, "env": env})
    ss = data["smartshift"]
    plan = dict(ss["plan"])
    fd = plan.pop("forecastData") or {}

    result = dict(plan)
    boi = ss.get("batteryOverridesInfo") or {}
    result["override"] = boi.get("effectiveOverride")
    result["during_control_summary"] = boi.get("duringControlSummary")

    if fd.get("__typename") == "SmartShiftDataError":
        result["past"], result["forecast"] = [], []
        result["forecast_error"] = {"type": fd.get("type"), "title": fd.get("title"), "message": fd.get("message")}
    else:
        result["past"] = (fd.get("past") or [])[-past_count:][::-1]
        result["forecast"] = (fd.get("forecast") or [])[:forecast_count]
        result["forecast_error"] = fd.get("forecastError")

    return result



# -----------------------------------------------------------------------------
# Writes
# -----------------------------------------------------------------------------

def set_smartshift(id_token: str, site_id: str, config_id: str, enabled: bool) -> bool:
    data = graphql(
        id_token, SET_SMARTSHIFT,
        {"input": {"deviceId": f"CONFIG#{config_id}", "optimisationEnabled": enabled}},
    )
    return data["updateSmartShiftDeviceSettings"]["settings"]["optimisationEnabled"]


def _cancel_override_id(id_token: str, site_id: str, config_id: str, override_id: str) -> None:
    """Cancel a specific override by ID, without polling stats first."""
    graphql(
        id_token, CANCEL_OVERRIDE,
        {"input": {"siteId": site_id, "configId": config_id, "overrideId": override_id}},
    )


def cancel_override(id_token: str, site_id: str, config_id: str) -> str | None:
    stats = get_stats(id_token, site_id)
    override = stats.get("override")
    if not override:
        print("No active override to cancel.")
        return None
    _cancel_override_id(id_token, site_id, config_id, override["overrideId"])
    return override["value"]


def add_override(id_token: str, site_id: str, config_id: str, value: str, duration_minutes: int) -> dict:
    """
    Applies a battery override. Cancels whatever's currently running first
    (only one override can be active at a time), and auto-enables Smart
    Shift first if it's off - Amber silently ignores overrides applied
    while Smart Shift is disabled, so this avoids the override quietly
    doing nothing. Matches api.py's async_set_override exactly.
    """
    stats = get_stats(id_token, site_id)

    if not stats.get("smartshift_enabled"):
        print("Smart Shift is off - enabling it first (required for overrides to work)...")
        set_smartshift(id_token, site_id, config_id, True)
        time.sleep(SMARTSHIFT_ENABLE_SETTLE_SECONDS)

    if stats.get("override"):
        print(f"Cancelling active override ({stats['override']['value']}) first...")
        _cancel_override_id(id_token, site_id, config_id, stats["override"]["overrideId"])
        time.sleep(OVERRIDE_SETTLE_SECONDS)

    now = datetime.now(timezone.utc)
    data = graphql(
        id_token, ADD_OVERRIDE,
        {
            "input": {
                "siteId": site_id,
                "configId": config_id,
                "overrideValue": value,
                "validFrom": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "validTo": (now + timedelta(minutes=duration_minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
        },
    )
    return data["smartshift"]["addBatteryOverride"]


# -----------------------------------------------------------------------------
# Output helpers
# -----------------------------------------------------------------------------

def money(cents) -> str:
    """Format cents as a signed dollar string, e.g. -$0.04 not $-0.04."""
    dollars = (cents or 0) / 100
    return f"{'-' if dollars < 0 else ' '}${abs(dollars):5.2f}"


def print_stats(stats: dict) -> None:
    soc = stats.get("soc")
    print(f"Battery:      {soc}%" if soc is not None else "Battery:      offline")
    if stats.get("battery_power_w") is not None:
        print(f"Power:        {stats['battery_power_w']}W")
    print(f"Smart Shift:  {'on' if stats.get('smartshift_enabled') else 'off'}")
    override = stats.get("override")
    if override:
        print(f"Override:     {override.get('value')} (ends {override.get('validTo') or override.get('estimatedEndDate') or 'unknown'})")
    else:
        print("Override:     none")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    try:
        import pycognito  # noqa: F401
    except ModuleNotFoundError:
        print("ERROR: pycognito isn't installed.")
        print("  pip3 install pycognito --break-system-packages")
        print("")
        print("If that fails (permission denied, or pip isn't available at all -")
        print("some locked-down Home Assistant containers don't allow installing")
        print("packages into their own Python environment), this script doesn't")
        print("need to run inside Home Assistant at all - it only needs network")
        print("access to Amber's API. Copy amber_graphql.py to your own computer")
        print("and run it there instead.")
        sys.exit(1)

    email = os.environ.get("AMBER_EMAIL")
    password = os.environ.get("AMBER_PASSWORD")
    if not email or not password:
        print("ERROR: Set AMBER_EMAIL and AMBER_PASSWORD environment variables first.")
        print("  export AMBER_EMAIL=\"you@example.com\"")
        print("  export AMBER_PASSWORD=\"your amber app password\"")
        sys.exit(1)

    commands = (
        "live, live-detail, status, usage, prices, plan, discharge, charge, "
        "preserve-charge, consume, cancel, smartshift_on, smartshift_off"
    )

    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <command> [args]")
        print(f"Commands: {commands}")
        sys.exit(1)

    command = sys.argv[1].lower()

    print("Logging in...")
    id_token = cognito_login(email, password)
    site_id, config_id = discover_site(id_token)

    if command == "live":
        stats = get_stats(id_token, site_id)
        prices = get_live_prices(id_token, site_id)
        print(f"Buy:          {prices['buy_cents']:.0f}c/kWh" if prices["buy_cents"] is not None else "Buy:          unavailable")
        print(f"Sell:         {prices['sell_cents']:.0f}c/kWh" if prices["sell_cents"] is not None else "Sell:         unavailable")
        print_stats(stats)
        print(f"Import cost:  {money(prices['import_cost_cents'])}")
        print(f"Export earn:  {money(prices['export_earnings_cents'])}")
        print(f"Net:          {money(prices['net_earnings_cents'])}")

    elif command == "status":
        print_stats(get_stats(id_token, site_id))

    elif command == "live-detail":
        d = get_live_detail(id_token, site_id)
        print(f"Site power:   {d['sitePowerW']}W" + ("  (exporting)" if d['sitePowerW'] < 0 else "  (importing)" if d['sitePowerW'] > 0 else ""))
        print(f"Solar:        {d['solarPowerW']}W")
        print(f"House load:   {d['fixedLoadPowerW']}W")
        print(f"Battery:      {d['batteryPowerW']}W" + ("  (charging)" if d['batteryPowerW'] < 0 else "  (discharging)" if d['batteryPowerW'] > 0 else "  (idle)"))
        print(f"Battery SOC:  {d['stateOfChargePercentage']}%  ({d['batteryEnergyWh']:.0f}Wh of {d['batteryMaxEnergyWh']:.0f}Wh)")
        print(f"Buy:          {d['currentGeneralUsagePrice']:.0f}c/kWh")
        print(f"Sell:         {d['currentFeedInPrice']:.0f}c/kWh")
        print(f"Renewable:    {d['currentRenewablePercentage']}%")
        print(f"State:        {d['powerState']}")
        print(f"              {d['powerStateDescription']}")
        if d.get('powerStateActionTitle'):
            print(f"Action:       {d['powerStateActionTitle']} - {d['powerStateActionDescription']}")

    elif command == "usage":
        show_days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        u = get_usage(id_token, site_id)

        period = u["period_summary"]
        if period:
            print("\n--- Billing Period ---")
            print(f"Usage:      {period['usageKwh']:.1f}kWh")
            print(f"Net cost:   {money(period['costInCents'])}")
            print(f"Renewable:  {period['renewablePercentage']}%")

        print(f"\n--- Daily Usage (most recent {min(show_days, len(u['days']))} days) ---")
        for day in u["days"][-show_days:]:
            if day["status"] == "missing":
                print(f"  {day['date']}  no data")
                continue
            tag = " (estimated)" if day["status"] == "estimated" else ""
            imp_kwh = day["import_kwh"] or 0
            exp_kwh = day["export_kwh"] or 0
            renew = day["renewable_percentage"]
            line = (f"  {day['date']}{tag}  "
                    f"import {imp_kwh:5.1f}kWh ({money(day['import_cost_cents'])})  "
                    f"export {exp_kwh:5.1f}kWh ({money(day['export_earnings_cents'])})  "
                    f"net {money(day['net_cost_cents'])}")
            if renew is not None:
                line += f"  renewable {renew:.0f}%"
            if day["controlled_kwh"] is not None:
                line += f"  controlled {day['controlled_kwh']:.1f}kWh"
            print(line)

    elif command == "prices":
        p = get_prices(id_token, site_id)
        for label, key in (("Buy", "general"), ("Sell", "feed_in")):
            side = p[key]
            cur = side["current"]
            print(f"\n--- {label} ({key}) ---")
            if cur:
                tag = "" if cur["estimate"] else "  (live)"
                print(f"Now: {cur['kwhPriceInCents']:.0f}c/kWh{tag}  "
                      f"[{cur['indicator']}]  renewable {cur['renewablePercentage']}%")
            else:
                print("Now: unavailable")

            if side["forecast_5min"]:
                print("Next 5-min periods:", ", ".join(
                    f"{pd['start'][11:16]} {pd['kwhPriceInCents']:.0f}c" for pd in side["forecast_5min"]
                ))
            if side["forecast"]:
                print("Forecast (30-min):")
                for pd in side["forecast"]:
                    print(f"  {pd['start'][11:16]}  {pd['kwhPriceInCents']:5.0f}c/kWh  "
                          f"[{pd['indicator']:<9}]  renewable {pd['renewablePercentage']}%" +
                          ("  DEMAND WINDOW" if pd.get("demandWindow") else ""))
            if side["previous"]:
                print("Recent (30-min, most recent first):")
                for pd in side["previous"]:
                    print(f"  {pd['start'][11:16]}  {pd['kwhPriceInCents']:5.0f}c/kWh  [{pd['indicator']}]")

        remarks = [r for r in p["remarks"].values() if r]
        if remarks:
            print("\n--- Amber's notes ---")
            for r in remarks:
                print(f"  {r}")

    elif command == "plan":
        past_count = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        forecast_count = int(sys.argv[3]) if len(sys.argv) > 3 else 6
        pl = get_plan(id_token, site_id, past_count=past_count, forecast_count=forecast_count)

        print("--- Live ---")
        print(f"Site power:   {pl['sitePowerW']}W" + ("  (exporting)" if pl['sitePowerW'] < 0 else "  (importing)" if pl['sitePowerW'] > 0 else ""))
        print(f"Solar:        {pl['solarPowerW']}W")
        print(f"House load:   {pl['fixedLoadPowerW']}W")
        print(f"Battery:      {pl['batteryPowerW']}W" + ("  (charging)" if pl['batteryPowerW'] < 0 else "  (discharging)" if pl['batteryPowerW'] > 0 else "  (idle)"))
        print(f"Battery SOC:  {pl['stateOfChargePercentage']}%")
        print(f"State:        {pl['powerState']} - {pl['powerStateDescription']}")

        if pl["override"]:
            ov = pl["override"]
            print(f"\n--- Active Override ---")
            print(f"Value:        {ov.get('value')}")
            print(f"Ends:         {ov.get('validTo') or ov.get('estimatedEndDate') or 'unknown'}")
            if pl["during_control_summary"]:
                # duringControlSummary is a union type with no confirmed
                # populated example (null throughout the captured trace this
                # was built from, since no override was active at the time) -
                # shown as raw JSON rather than guessing at named fields.
                print(f"Summary (raw): {json.dumps(pl['during_control_summary'])}")

        def describe_period(p, label):
            desc = p.get("actionDescriptions") or {}
            header = desc.get("simpleHeader") or desc.get("header") or ""
            decisions = p.get("actionDecisions") or []
            reasons = "; ".join(
                f"{d.get('batteryAction') or d.get('solarAction')}: {d.get('reason')}"
                for d in decisions if d.get("batteryAction") or d.get("solarAction")
            )
            line = f"  {p['periodStart'][11:16]}  buy {p['generalUsagePriceCents']:.0f}c  sell {p['feedInPriceCents']:.0f}c"
            if header:
                line += f"  - {header}"
            print(line)
            if reasons:
                print(f"          {reasons}")

        if pl["past"]:
            print(f"\n--- Recent actions (most recent first) ---")
            for p_ in pl["past"]:
                describe_period(p_, "past")

        if pl["forecast_error"]:
            fe = pl["forecast_error"]
            print(f"\n--- Forecast unavailable: {fe.get('title')} - {fe.get('message')} ---")
        elif pl["forecast"]:
            print(f"\n--- Forecast (soonest first) ---")
            for p_ in pl["forecast"]:
                describe_period(p_, "forecast")

    elif command in ("discharge", "charge", "preserve-charge", "consume"):
        value = {
            "discharge": "discharge", "charge": "charge",
            "preserve-charge": "preserve-charge", "consume": "self-consume",
        }[command]
        duration = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        print(f"Applying '{value}' for {duration} minutes...")
        result = add_override(id_token, site_id, config_id, value, duration)
        print(f"Done. Override active until {result.get('validTo')}")

    elif command == "cancel":
        cancelled = cancel_override(id_token, site_id, config_id)
        if cancelled:
            print(f"Cancelled '{cancelled}'.")

    elif command == "smartshift_on":
        set_smartshift(id_token, site_id, config_id, True)
        print("Smart Shift enabled.")

    elif command == "smartshift_off":
        set_smartshift(id_token, site_id, config_id, False)
        print("Smart Shift disabled.")

    else:
        print(f"Unknown command: {command}")
        print(f"Commands: {commands}")
        sys.exit(1)


if __name__ == "__main__":
    main()
