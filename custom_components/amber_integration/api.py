"""Async client for the Amber Electric Smart Shift GraphQL API.

Ports the logic from the standalone amber_auth.py / amber_graphql.py scripts
into an async client suitable for a Home Assistant integration.

Authentication uses AWS Cognito via pycognito, which is blocking, so it is run
in an executor. All GraphQL traffic uses the shared aiohttp session.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from aiohttp import ClientSession

from .const import (
    COGNITO_CLIENT_ID,
    COGNITO_POOL_ID,
    GRAPHQL_URL,
    OVERRIDE_CONTINUITY_MINUTES,
    OVERRIDE_SETTLE_SECONDS,
    SMARTSHIFT_ENABLE_SETTLE_SECONDS,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class AmberAuthError(Exception):
    """Raised when authentication with Amber fails."""


class AmberApiError(Exception):
    """Raised when the Amber API returns an error."""


def parse_amber_timestamp(value: Any) -> datetime | None:
    """Parse Amber's UTC timestamp format.

    Tries the exact format seen on validTo first (with milliseconds), then
    falls back to fromisoformat for anything else - estimatedEndDate is a
    different field with no confirmed trace showing its exact format, so
    this is intentionally more tolerant than a single strptime pattern.
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.000Z").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        pass
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


# -----------------------------------------------------------------------------
# GraphQL documents
# -----------------------------------------------------------------------------

SITE_QUERY = """
query { smartshift { batterySetting { siteId selectedConfigId } } }
"""

# Split into two queries, polled on independent schedules by two separate
# coordinators. A single combined query was simpler but forced prices and
# battery telemetry onto the same poll interval - since prices only change
# every 5 minutes on Amber's side but battery telemetry is close to
# real-time, that meant either polling telemetry too slowly or polling
# prices (and burning API calls) far more often than they can change.

STATS_QUERY = """
query SmartShiftStats($siteId: String, $env: String) {
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
        plan(siteId: $siteId, env: $env) {
            batteryMaxEnergyWh
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


class AmberApi:
    """Talks to the Amber Smart Shift API, refreshing its token as needed."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        site_id: str | None = None,
        config_id: str | None = None,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self.site_id = site_id
        self.config_id = config_id

        self._id_token: str | None = None
        self._expires_at: datetime | None = None
        self._auth_lock = asyncio.Lock()

        # In-memory only, not persisted across restarts. Tracks which
        # override_id was applied by which "source" (manual/auto_buy/
        # auto_sell/service/...), so callers - specifically the automation
        # blueprints - can tell whether an override currently running is one
        # they themselves applied, before deciding whether to cancel it.
        #
        # Without this, any code path applying "charge" or "discharge"
        # looks identical from the outside - a manual toggle and Auto Buy's
        # own override both just show up as override_value == "charge". A
        # blueprint whose own rule conditions say "I shouldn't be running"
        # would cancel a manually-triggered override that happens to share
        # its value, which isn't its override to cancel.
        self._known_override_id: str | None = None
        self._known_override_source: str | None = None

        # Same idea, for Smart Shift's on/off state. Unlike an override,
        # there's no ID from Amber to reconcile against here - Smart Shift
        # is just a boolean - so this is tracked purely by who last called
        # async_set_smartshift() through THIS integration. Only meaningful
        # while Smart Shift is off: cleared the moment anything turns it
        # back on, since there's nothing left to attribute at that point.
        self._known_smartshift_off_source: str | None = None

    # -- authentication ----------------------------------------------------

    def _cognito_login(self) -> tuple[str, datetime]:
        """Blocking Cognito login. Must be run in an executor."""
        from pycognito import Cognito

        cognito = Cognito(
            COGNITO_POOL_ID,
            COGNITO_CLIENT_ID,
            username=self._email,
        )
        cognito.authenticate(password=self._password)
        # Amber tokens last an hour; refresh a little early to be safe.
        return cognito.id_token, datetime.now(timezone.utc) + timedelta(minutes=55)

    async def async_authenticate(self, hass_executor) -> None:
        """Authenticate and cache the token."""
        try:
            token, expires = await hass_executor(self._cognito_login)
        except Exception as err:  # pycognito raises botocore errors
            raise AmberAuthError(str(err)) from err

        self._id_token = token
        self._expires_at = expires
        _LOGGER.debug("Amber authentication succeeded, token valid until %s", expires)

    async def _async_ensure_token(self, hass_executor) -> str:
        """Return a valid token, refreshing it if expired."""
        async with self._auth_lock:
            if (
                self._id_token is None
                or self._expires_at is None
                or datetime.now(timezone.utc) >= self._expires_at
            ):
                await self.async_authenticate(hass_executor)
            return self._id_token  # type: ignore[return-value]

    # -- transport ---------------------------------------------------------

    async def _async_graphql(
        self, hass_executor, query: str, variables: dict | None = None
    ) -> dict[str, Any]:
        token = await self._async_ensure_token(hass_executor)

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with self._session.post(
            GRAPHQL_URL,
            json=payload,
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        ) as resp:
            body = await resp.json()

        if "errors" in body:
            messages = "; ".join(e.get("message", "") for e in body["errors"])
            raise AmberApiError(messages)

        return body["data"]

    async def async_graphql(
        self, hass_executor, query: str, variables: dict | None = None
    ) -> dict[str, Any]:
        """Public entry point for authenticated GraphQL calls.

        Exists so companion integrations that depend on this one (e.g. the
        Amber Price Timeline add-on) can reuse this client's cached Cognito
        token and connection instead of authenticating separately - one
        login/password, not several. Companion integrations own their own
        query text and response parsing; this only handles auth + transport.
        """
        return await self._async_graphql(hass_executor, query, variables)

    # -- discovery ---------------------------------------------------------

    async def async_discover_site(self, hass_executor) -> tuple[str, str]:
        """Fetch the site ID and battery config ID for this account."""
        data = await self._async_graphql(hass_executor, SITE_QUERY)
        setting = data["smartshift"]["batterySetting"]
        self.site_id = setting["siteId"]
        self.config_id = setting["selectedConfigId"]
        return self.site_id, self.config_id

    # -- polling -----------------------------------------------------------

    async def async_get_stats(self, hass_executor) -> dict[str, Any]:
        """Poll battery state, Smart Shift status and any active override.

        This is the fast-changing side of the old combined query - the
        stuff worth polling every few seconds. Prices are on their own
        slower poll via async_get_prices(), since Amber only updates those
        every 5 minutes regardless of how often this is called.

        Also picks up batteryMaxEnergyWh (total usable capacity) from
        smartshift.plan() - confirmed present there via a captured Plan tab
        trace, not exposed by smartshift.live() itself. Deliberately not a
        separate query: this value is effectively static, so there's no
        reason to poll it on its own schedule - piggybacking one extra
        field onto the existing stats poll is enough.

        Amber returns null for stateOfChargePercentage when it cannot reach
        the battery, so that lookup falls back with `or` rather than
        dict.get defaults.
        """
        data = await self._async_graphql(
            hass_executor, STATS_QUERY, {"siteId": self.site_id, "env": "prod"}
        )

        ss = data.get("smartshift") or {}
        live = ss.get("live") or {}
        override = (ss.get("batteryOverridesInfo") or {}).get("effectiveOverride")
        plan = ss.get("plan") or {}
        strategy = data.get("smartshiftBatteryStrategyConfig") or {}

        soc_raw = live.get("stateOfChargePercentage")

        # override_ends prefers validTo, falling back to estimatedEndDate.
        # Amber's schema has both on effectiveOverride, and there's a real
        # possibility not every override type populates validTo the same
        # way (self-consume specifically was seen with validTo empty while
        # active) - untested against a confirmed trace either way, so this
        # is a defensive fallback, not a confirmed fix. The raw values are
        # also exposed as sensor attributes on Manual Action Ends for
        # debugging if this still comes up empty.
        override_ends = None
        if override:
            override_ends = override.get("validTo") or override.get("estimatedEndDate")

        # Reconcile ownership tracking against what Amber actually reports.
        # If the polled override_id doesn't match what we last recorded -
        # cancelled and reapplied by something else, applied via the Amber
        # app directly, or this is the first poll since a restart - the
        # source is genuinely unknown, and that's what gets reported rather
        # than stale/wrong attribution.
        polled_override_id = override.get("overrideId") if override else None
        if polled_override_id != self._known_override_id:
            self._known_override_id = polled_override_id
            self._known_override_source = None
        override_source = self._known_override_source if polled_override_id else None

        return {
            "soc": soc_raw,
            "battery_online": soc_raw is not None,
            "battery_power": live.get("batteryPowerW"),
            "battery_capacity": plan.get("batteryMaxEnergyWh"),
            "power_state": live.get("powerState"),
            "power_state_description": live.get("powerStateDescription"),
            "override_value": override.get("value") if override else None,
            "override_id": override.get("overrideId") if override else None,
            "override_state": override.get("state") if override else None,
            "override_ends": override_ends,
            "override_source": override_source,
            "smartshift_enabled": strategy.get("status") == "enabled",
            # Only meaningful while off - if the poll shows Smart Shift is
            # actually on, there's nothing to attribute regardless of what
            # was last tracked, so this reports None rather than a stale
            # source from before it was turned back on.
            "smartshift_off_source": (
                self._known_smartshift_off_source
                if strategy.get("status") != "enabled"
                else None
            ),
        }

    async def async_get_prices(self, hass_executor) -> dict[str, Any]:
        """Poll current buy/sell prices and this interval's earnings.

        Amber returns null for liveMetrics between intervals, so that
        lookup falls back with `or` rather than dict.get defaults.
        """
        data = await self._async_graphql(
            hass_executor, PRICE_QUERY, {"siteId": self.site_id}
        )

        live = (data.get("smartshift") or {}).get("live") or {}
        metrics = live.get("liveMetrics") or {}

        buy_cents = live.get("currentGeneralUsagePrice")
        sell_cents = live.get("currentFeedInPrice")

        return {
            # Prices come back in cents, converted to $/kWh for HA
            "buy_price": round(buy_cents / 100, 4) if buy_cents is not None else None,
            "sell_price": round(sell_cents / 100, 4) if sell_cents is not None else None,
            "import_cost": round(metrics.get("importCostsCents") or 0, 4),
            "export_earnings": round(metrics.get("exportEarningsCents") or 0, 4),
            "total_earnings": round(metrics.get("totalEarningsCents") or 0, 4),
        }

    # -- control -----------------------------------------------------------

    async def _async_cancel_override_id(self, hass_executor, override_id: str) -> None:
        """Cancel a specific override by ID, without polling stats first.

        Split out from async_cancel_override() so async_set_override() can
        cancel the override it already knows about (from its own earlier
        stats poll) without a second, redundant poll purely to rediscover
        the same override_id it's already holding.
        """
        await self._async_graphql(
            hass_executor,
            CANCEL_OVERRIDE,
            {
                "input": {
                    "siteId": self.site_id,
                    "configId": self.config_id,
                    "overrideId": override_id,
                }
            },
        )
        self._known_override_id = None
        self._known_override_source = None

    async def async_cancel_override(self, hass_executor) -> str | None:
        """Cancel the active override. Returns the cancelled value, if any."""
        stats = await self.async_get_stats(hass_executor)
        override_id = stats.get("override_id")
        if not override_id:
            _LOGGER.debug("No active override to cancel")
            return None

        await self._async_cancel_override_id(hass_executor, override_id)
        return stats.get("override_value")

    async def async_set_override(
        self,
        hass_executor,
        value: str,
        duration_minutes: int,
        source: str | None = None,
    ) -> dict[str, Any] | None:
        """Apply a battery override.

        If the same override is already running with enough time left, it is
        left alone and None is returned - this avoids a needless cancel/reapply
        cycle every poll. A different override is cancelled first.

        source identifies the caller ("manual", "auto_buy", "auto_sell", ...)
        so a later poll can report who currently owns the active override -
        see _known_override_source above. Left as None for callers that
        don't need this (the raw services default to "service").

        Returns a dict with an added "_smartshift_was_enabled" key set True if
        Smart Shift had to be turned on to make the override take effect, so
        callers can reflect that in their own state rather than showing a
        stale "off" until the next poll. None is returned when the override
        was already running and nothing needed doing.
        """
        stats = await self.async_get_stats(hass_executor)

        # Amber silently ignores overrides while Smart Shift is disabled -
        # the call succeeds and does nothing - so it is re-enabled first,
        # deliberately, rather than letting the override quietly fail.
        #
        # This does mean that turning on a manual override re-enables Smart
        # Shift even if it had been switched off on purpose. That is the
        # intended trade-off: a control that appears to work but silently
        # does nothing is worse than one that changes a related setting and
        # reports it (see "_smartshift_was_enabled" below).
        smartshift_was_enabled = False
        if not stats.get("smartshift_enabled"):
            _LOGGER.debug("Smart Shift disabled, re-enabling before override")
            await self.async_set_smartshift(hass_executor, True)
            smartshift_was_enabled = True
            await asyncio.sleep(SMARTSHIFT_ENABLE_SETTLE_SECONDS)

        current = stats.get("override_value")
        if current == value and stats.get("override_ends"):
            ends = parse_amber_timestamp(stats["override_ends"])
            remaining = (
                (ends - datetime.now(timezone.utc)).total_seconds() / 60
                if ends is not None
                else 0
            )

            if remaining >= OVERRIDE_CONTINUITY_MINUTES:
                _LOGGER.debug(
                    "Override '%s' already active with %.1f min remaining, leaving it",
                    value,
                    remaining,
                )
                return None

        if current:
            _LOGGER.debug("Cancelling '%s' before applying '%s'", current, value)
            await self._async_cancel_override_id(hass_executor, stats["override_id"])
            await asyncio.sleep(OVERRIDE_SETTLE_SECONDS)

        now = datetime.now(timezone.utc)
        data = await self._async_graphql(
            hass_executor,
            ADD_OVERRIDE,
            {
                "input": {
                    "siteId": self.site_id,
                    "configId": self.config_id,
                    "overrideValue": value,
                    "validFrom": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "validTo": (
                        now + timedelta(minutes=duration_minutes)
                    ).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                }
            },
        )
        result = dict(data["smartshift"]["addBatteryOverride"])
        result["_smartshift_was_enabled"] = smartshift_was_enabled
        self._known_override_id = result.get("overrideId")
        self._known_override_source = source
        return result

    async def async_set_smartshift(
        self, hass_executor, enabled: bool, source: str | None = None
    ) -> bool:
        """Enable or disable Smart Shift optimisation.

        source identifies the caller, the same way async_set_override()
        does - recorded only when turning Smart Shift OFF, since that's the
        only direction the "Auto Disable Smart Shift When Idle" blueprint
        needs to know about (it only ever wants to turn Smart Shift back ON
        if IT was the one that turned it off - see _known_smartshift_off_source
        above). Turning it on, from any source, clears the tracking - there's
        no "off source" left to attribute once it's on.
        """
        data = await self._async_graphql(
            hass_executor,
            SET_SMARTSHIFT,
            {
                "input": {
                    "deviceId": f"CONFIG#{self.config_id}",
                    "optimisationEnabled": enabled,
                }
            },
        )
        result = data["updateSmartShiftDeviceSettings"]["settings"]["optimisationEnabled"]
        self._known_smartshift_off_source = source if not enabled else None
        return result
