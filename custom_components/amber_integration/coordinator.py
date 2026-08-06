"""Polling coordinators for the Amber Electric Custom integration.

Two independent coordinators, not one - see const.py for why. Each polls a
purpose-built lean query (api.py) on its own schedule, so fast telemetry
polling doesn't also re-fetch prices that can't have changed yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AmberApi, AmberApiError, AmberAuthError
from .const import (
    CONF_PRICE_SCAN_INTERVAL,
    CONF_STATS_SCAN_INTERVAL,
    DEFAULT_OVERRIDE_DURATION,
    DEFAULT_PRICE_SCAN_INTERVAL,
    DEFAULT_STATS_SCAN_INTERVAL,
    DOMAIN,
    PRICE_POLL_BLOCK_MINUTES,
    PRICE_POLL_OFFSET_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


def _configured_interval(entry: ConfigEntry, key: str, default: int) -> int:
    """Read a poll interval, preferring options over the original entry data.

    Options are what the Configure dialog writes; entry data only carries a
    value for entries created before a given option existed. Falling through
    options -> data -> default in that order means an upgrade never loses a
    user's setting, and a fresh install still gets a sensible number.
    """
    return entry.options.get(key, entry.data.get(key, default))


class _AmberBaseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Shared plumbing for the stats and price coordinators."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: AmberApi,
        name: str,
        interval_seconds: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(seconds=interval_seconds),
        )
        self.api = api
        self.entry = entry
        # Tracked explicitly rather than relying on a coordinator built-in -
        # the "Last Stats/Price Poll" sensors need a genuine confirmed-poll
        # timestamp, set only here (not by the switches' optimistic writes,
        # which use async_set_updated_data() directly and don't go through
        # _async_fetch - an optimistic write isn't a confirmed poll).
        self.last_success_time: datetime | None = None

    @property
    def executor(self):
        """Executor used for the blocking Cognito calls."""
        return self.hass.async_add_executor_job

    async def _async_fetch(self, api_method) -> dict[str, Any]:
        try:
            data = await api_method(self.executor)
        except AmberAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Amber authentication failed: {err}"
            ) from err
        except AmberApiError as err:
            raise UpdateFailed(f"Amber API error: {err}") from err
        self.last_success_time = datetime.now(timezone.utc)
        return data


class AmberStatsCoordinator(_AmberBaseCoordinator):
    """Polls battery state, Smart Shift status and any active override.

    Fast schedule (default 30s) - this is the side of the old combined poll
    that's actually worth checking often, since battery telemetry is close
    to real-time on Amber's side.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: AmberApi) -> None:
        interval = _configured_interval(
            entry, CONF_STATS_SCAN_INTERVAL, DEFAULT_STATS_SCAN_INTERVAL
        )
        super().__init__(hass, entry, api, f"{DOMAIN}_stats", interval)
        # Duration used by the manual override switches, set via the paired
        # "Manual Toggle Duration" number entity. Seeded with the default
        # here, then overwritten during startup by that entity restoring
        # its previous value (see _AmberRestoringNumber in number.py), so
        # in practice a restart keeps whatever was last set.
        self.override_duration_minutes: int = DEFAULT_OVERRIDE_DURATION

    async def _async_update_data(self) -> dict[str, Any]:
        return await self._async_fetch(self.api.async_get_stats)


class AmberPriceCoordinator(_AmberBaseCoordinator):
    """Polls current buy/sell prices and this interval's earnings.

    Aligned to the wall clock, not to a fixed interval from the last run.
    Amber publishes prices on 5-minute market boundaries, so polling is
    scheduled for PRICE_POLL_OFFSET_SECONDS past each boundary - :00:30,
    :05:30, :10:30 and so on. Polling on a plain repeating interval would
    drift relative to those boundaries and could sit just before one,
    consistently reading the previous interval's price.

    The offset exists because Amber's own publish isn't instant at the
    boundary - asking exactly on the minute can still return the previous
    interval, so this waits a beat before asking.

    Set a custom Market Price Poll Interval to opt out of alignment and go
    back to a plain repeating timer.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: AmberApi) -> None:
        configured = _configured_interval(
            entry, CONF_PRICE_SCAN_INTERVAL, DEFAULT_PRICE_SCAN_INTERVAL
        )
        # Alignment only applies at the default. A user who has deliberately
        # chosen their own interval gets exactly that interval instead - it
        # would be surprising to set 60s and still be polled on 5-minute
        # boundaries.
        self._aligned = configured == DEFAULT_PRICE_SCAN_INTERVAL
        super().__init__(hass, entry, api, f"{DOMAIN}_price", configured)

    def _seconds_until_next_slot(self) -> float:
        """Seconds until the next PRICE_POLL_OFFSET past a 5-minute boundary."""
        now = datetime.now(timezone.utc)
        minutes_into_block = now.minute % PRICE_POLL_BLOCK_MINUTES
        seconds_into_block = (
            minutes_into_block * 60 + now.second + now.microsecond / 1_000_000
        )
        block_seconds = PRICE_POLL_BLOCK_MINUTES * 60
        target = PRICE_POLL_OFFSET_SECONDS

        if seconds_into_block < target:
            # The slot for the current block hasn't passed yet
            return target - seconds_into_block
        return block_seconds - seconds_into_block + target

    async def _async_update_data(self) -> dict[str, Any]:
        data = await self._async_fetch(self.api.async_get_prices)
        if self._aligned:
            # Re-point the timer at the next wall-clock slot after every
            # run, so a slow request or a restart at an awkward moment
            # doesn't permanently skew the schedule.
            self.update_interval = timedelta(seconds=self._seconds_until_next_slot())
        return data


@dataclass
class AmberRuntimeData:
    """Holds both coordinators for a config entry.

    Entity platforms pick whichever one their data actually comes from -
    battery/override/Smart Shift entities use .stats, price and interval
    earnings entities use .price.
    """

    stats: AmberStatsCoordinator
    price: AmberPriceCoordinator
