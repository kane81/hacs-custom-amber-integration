"""The Amber Electric Custom integration.

Provides the core Amber data and control surface:
  - sensors for prices, battery state, earnings and manual override status
  - binary sensors for battery connectivity and whether an override is running
  - a switch for Smart Shift optimisation, plus four manual override toggles
  - a number for how long a manual override should hold
  - a button to force an immediate poll
  - services mirroring the override controls, for use from automations

Polls on two independent schedules (see coordinator.py / const.py) - fast
for battery telemetry, slow for prices, since the two change at very
different rates on Amber's side.

This is Part 1 of the project and works standalone. Part 2 (a ready-made
automation suite and dashboard, installed separately by install.sh) builds
on top of these entities but is entirely optional.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AmberApi, AmberApiError, AmberAuthError
from .const import (
    ATTR_DURATION,
    ATTR_SOURCE,
    CONF_CONFIG_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SITE_ID,
    DEFAULT_OVERRIDE_DURATION,
    DOMAIN,
    OVERRIDE_SETTLE_SECONDS,
    OVERRIDE_CHARGE,
    OVERRIDE_CONSUME,
    OVERRIDE_DISCHARGE,
    OVERRIDE_PRESERVE,
    SERVICE_CANCEL_OVERRIDE,
    SERVICE_CONSUME,
    SERVICE_FORCE_CHARGE,
    SERVICE_FORCE_DISCHARGE,
    SERVICE_PRESERVE_CHARGE,
    SERVICE_REFRESH,
    SERVICE_SMARTSHIFT_OFF,
    SERVICE_SMARTSHIFT_ON,
)
from .coordinator import AmberPriceCoordinator, AmberRuntimeData, AmberStatsCoordinator

_LOGGER = logging.getLogger(__name__)

# Every service this integration registers. Single source of truth for both
# registration (_async_register_services) and teardown (async_unload_entry) -
# these were previously two separate hardcoded lists that had to be kept in
# step by hand, so a service added to one and not the other would linger
# after the last config entry was removed.
ALL_SERVICES: tuple[str, ...] = (
    SERVICE_FORCE_CHARGE,
    SERVICE_FORCE_DISCHARGE,
    SERVICE_PRESERVE_CHARGE,
    SERVICE_CONSUME,
    SERVICE_CANCEL_OVERRIDE,
    SERVICE_SMARTSHIFT_ON,
    SERVICE_SMARTSHIFT_OFF,
    SERVICE_REFRESH,
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]

DURATION_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DURATION, default=DEFAULT_OVERRIDE_DURATION): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1440)
        ),
        vol.Optional(ATTR_SOURCE, default="service"): str,
    }
)

# Smart Shift on/off take a source too - no duration, since Smart Shift is
# just a boolean, not a timed override.
SMARTSHIFT_SCHEMA = vol.Schema({vol.Optional(ATTR_SOURCE, default="service"): str})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amber from a config entry."""
    api = AmberApi(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_SITE_ID),
        entry.data.get(CONF_CONFIG_ID),
    )

    stats_coordinator = AmberStatsCoordinator(hass, entry, api)
    price_coordinator = AmberPriceCoordinator(hass, entry, api)

    # Auth failure on the first stats refresh would also fail on price - no
    # need to run both if the first one already proves the credentials work.
    await stats_coordinator.async_config_entry_first_refresh()
    await price_coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = AmberRuntimeData(
        stats=stats_coordinator, price=price_coordinator
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            for service in ALL_SERVICES:
                hass.services.async_remove(DOMAIN, service)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the override services, once.

    Overrides, cancel and Smart Shift on/off all act through the STATS
    coordinator - that's the one whose data includes override_value and
    smartshift_enabled. Refresh still touches both, since it's meant as a
    general "poll now" for either kind of data.
    """
    if hass.services.has_service(DOMAIN, SERVICE_FORCE_CHARGE):
        return

    def _runtime_data() -> list[AmberRuntimeData]:
        return list(hass.data.get(DOMAIN, {}).values())

    async def _run_on_each(
        operation: Callable[[AmberStatsCoordinator], Awaitable[Any]],
        error_message: str,
    ) -> None:
        """Run one API operation against every configured Amber account.

        Every mutating service shares the same shape: call the API, turn any
        API error into something Home Assistant can show the user, wait out
        Amber's propagation delay, then refresh so entities reflect reality.

        On failure this also raises a persistent_notification - the single
        place that happens, regardless of whether the call came from a
        dashboard button, a manual service call, or Auto Sell/Auto Buy.
        Success is silent by design; routine charge/discharge/cancel
        activity is visible on the dashboard status line instead, so a
        notification only fires when something actually needs attention.

        The sleep is why the delay exists at all - Amber's backend takes a
        few seconds to apply a mutation, so refreshing immediately gets the
        pre-change state back. The switches solve this with an optimistic
        write instead (see switch.py); services have no entity state of
        their own to write optimistically, so they wait.
        """
        for data in _runtime_data():
            coordinator = data.stats
            try:
                await operation(coordinator)
            except (AmberApiError, AmberAuthError) as err:
                message = f"{error_message}: {err}"
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {"title": "Amber Smart Shift error", "message": message},
                )
                raise HomeAssistantError(message) from err
            await asyncio.sleep(OVERRIDE_SETTLE_SECONDS)
            await coordinator.async_request_refresh()

    def _make_override_handler(value: str):
        """Build the service handler for one override value.

        A factory rather than a loop variable closure - binding `value` as a
        parameter here avoids the late-binding trap where every registered
        handler would end up using whichever value the loop finished on.
        """

        async def handler(call: ServiceCall) -> None:
            duration = call.data.get(ATTR_DURATION, DEFAULT_OVERRIDE_DURATION)
            source = call.data.get(ATTR_SOURCE, "service")
            await _run_on_each(
                lambda c: c.api.async_set_override(
                    c.executor, value, duration, source=source
                ),
                f"Amber '{value}' override failed",
            )

        return handler

    def _make_smartshift_handler(enabled: bool):
        async def handler(call: ServiceCall) -> None:
            source = call.data.get(ATTR_SOURCE, "service")
            await _run_on_each(
                lambda c: c.api.async_set_smartshift(c.executor, enabled, source=source),
                "Smart Shift change failed",
            )

        return handler

    async def handle_cancel(call: ServiceCall) -> None:
        await _run_on_each(
            lambda c: c.api.async_cancel_override(c.executor),
            "Cancel override failed",
        )

    async def handle_refresh(call: ServiceCall) -> None:
        # No mutation, so no settle delay and nothing to translate - and it
        # refreshes BOTH coordinators, unlike the mutating services which
        # only touch stats.
        for data in _runtime_data():
            await data.stats.async_request_refresh()
            await data.price.async_request_refresh()

    # (service name, handler, schema)
    services: tuple[tuple[str, Any, vol.Schema], ...] = (
        (SERVICE_FORCE_CHARGE, _make_override_handler(OVERRIDE_CHARGE), DURATION_SCHEMA),
        (SERVICE_FORCE_DISCHARGE, _make_override_handler(OVERRIDE_DISCHARGE), DURATION_SCHEMA),
        (SERVICE_PRESERVE_CHARGE, _make_override_handler(OVERRIDE_PRESERVE), DURATION_SCHEMA),
        (SERVICE_CONSUME, _make_override_handler(OVERRIDE_CONSUME), DURATION_SCHEMA),
        (SERVICE_CANCEL_OVERRIDE, handle_cancel, vol.Schema({})),
        (SERVICE_SMARTSHIFT_ON, _make_smartshift_handler(True), SMARTSHIFT_SCHEMA),
        (SERVICE_SMARTSHIFT_OFF, _make_smartshift_handler(False), SMARTSHIFT_SCHEMA),
        (SERVICE_REFRESH, handle_refresh, vol.Schema({})),
    )
    for service_name, handler, schema in services:
        hass.services.async_register(DOMAIN, service_name, handler, schema=schema)
