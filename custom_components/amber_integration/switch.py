"""Smart Shift switch and manual override toggles for the Amber Electric
Custom integration.

Only one battery override can be active on Amber's side at a time, so the
four manual override toggles are mutually exclusive: turning one on cancels
whichever was previously active. Each toggle's is_on state is derived live
from the coordinator's shared data (whichever override value the last poll
or optimistic update reported), so this happens automatically with no extra
bookkeeping - as soon as one toggle updates the shared data, every sibling
toggle's is_on recalculates correctly.

Optimistic updates go through coordinator.async_set_updated_data() rather
than mutating coordinator.data directly, because that is the only way to
also notify sibling entities to re-render immediately - directly mutating
the dict and calling self.async_write_ha_state() only updates the one
entity that made the call, leaving the others showing stale state until the
next real poll.

None of these methods call async_request_refresh() after the optimistic
write. Amber's backend has a real propagation delay after a mutation
succeeds - an immediate re-poll consistently returns the PRE-change state,
which would overwrite the correct optimistic write with stale data for one
poll cycle (observed: a toggle correctly shows on, then flips back off ~1
second later, then corrects itself back to on once the next scheduled poll
runs ~30s after that). Relying on the optimistic write plus the normal
scheduled poll avoids that entirely - the poll interval is short enough by
then that there's no meaningful downside to not confirming immediately.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .api import AmberApiError, AmberAuthError
from .const import (
    DOMAIN,
    OVERRIDE_CHARGE,
    OVERRIDE_CONSUME,
    OVERRIDE_DISCHARGE,
    OVERRIDE_PRESERVE,
)
from .coordinator import AmberRuntimeData, AmberStatsCoordinator
from .entity import AmberEntity

_LOGGER = logging.getLogger(__name__)

# The Part 2 automation on/off switches. These only mean anything if you've
# set up the automation blueprints - on a Part-1-only install they sit inert
# in the Configuration section. They live in Part 1 because a blueprint
# cannot create helpers, so anything an automation references must already
# exist as an entity.
#
# There's no separate master "Enable Auto Sell"/"Enable Auto Buy" switch -
# each of the three rules per direction has its own on/off, and a direction
# is effectively active whenever at least one of its rules is both enabled
# and its battery condition is currently satisfied. A single master switch
# on top of that would just be a second layer asking "why isn't Rule 1
# running even though it's on?" - "because the master switch is also off" -
# which is exactly the extra complexity being avoided here.
#
# All default OFF, so a fresh install never starts moving the battery on its
# own before you've set your thresholds.
AUTOMATION_ENABLE_SWITCHES: tuple[tuple[str, str, str], ...] = (
    # (key, name, icon)
    ("enable_sell_rule_1", "Enable Sell Rule 1", "mdi:transmission-tower-export"),
    ("enable_sell_rule_2", "Enable Sell Rule 2", "mdi:transmission-tower-export"),
    ("enable_sell_rule_3", "Enable Sell Rule 3", "mdi:transmission-tower-export"),
    ("enable_buy_rule_1", "Enable Buy Rule 1", "mdi:battery-charging-high"),
    ("enable_buy_rule_2", "Enable Buy Rule 2", "mdi:battery-charging-high"),
    ("enable_buy_rule_3", "Enable Buy Rule 3", "mdi:battery-charging-high"),
    ("enable_auto_smart_shift_off", "Auto Disable Smart Shift When Idle", "mdi:weather-night"),
)

MANUAL_OVERRIDE_SWITCHES: tuple[tuple[str, str, str, str], ...] = (
    # (key, name, icon, override_value)
    ("manual_discharge", "Manual Discharge", "mdi:battery-arrow-down", OVERRIDE_DISCHARGE),
    ("manual_charge", "Manual Charge", "mdi:battery-arrow-up", OVERRIDE_CHARGE),
    ("manual_preserve", "Manual Preserve", "mdi:battery-lock", OVERRIDE_PRESERVE),
    ("manual_self_consumption", "Manual Self Consumption", "mdi:home-battery", OVERRIDE_CONSUME),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Smart Shift switch and manual override toggles.

    All from the stats coordinator - smartshift_enabled and override_value
    are both stats-domain fields, not price ones.
    """
    data: AmberRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.stats
    entities: list[SwitchEntity] = [AmberSmartShiftSwitch(coordinator)]
    entities.extend(
        AmberManualOverrideSwitch(coordinator, key, name, icon, override_value)
        for key, name, icon, override_value in MANUAL_OVERRIDE_SWITCHES
    )
    entities.extend(
        AmberAutomationEnableSwitch(coordinator, key, name, icon)
        for key, name, icon in AUTOMATION_ENABLE_SWITCHES
    )
    async_add_entities(entities)


class AmberSmartShiftSwitch(AmberEntity, SwitchEntity):
    """Turns Amber's Smart Shift optimisation on and off.

    Turning this off is what stops the Smart Shift plan dispatching the
    battery. Battery overrides are ignored by Amber while it is off.
    """

    _attr_name = "Enable Smart Shift"
    _attr_icon = "mdi:auto-fix"

    def __init__(self, coordinator: AmberStatsCoordinator) -> None:
        super().__init__(coordinator, "smartshift")

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("smartshift_enabled")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return {
            # Who last turned Smart Shift off through this integration
            # ("manual", "auto_disable_smart_shift_when_idle", "service",
            # ...), or None if it's currently on, or off for a reason this
            # integration didn't track (turned off via the Amber app
            # directly, for instance). The "Auto Disable Smart Shift When
            # Idle" blueprint checks this before turning Smart Shift back
            # on, so it only ever undoes its own action - never a manual
            # toggle, and never anything it wasn't responsible for.
            "off_source": self.coordinator.data.get("smartshift_off_source"),
        }

    async def _async_set(self, enabled: bool) -> None:
        try:
            await self.coordinator.api.async_set_smartshift(
                self.coordinator.executor, enabled, source="manual"
            )
        except (AmberApiError, AmberAuthError) as err:
            raise HomeAssistantError(f"Could not change Smart Shift: {err}") from err

        # Reflect the change immediately via the optimistic write below.
        # Deliberately NOT calling async_request_refresh() here - Amber's
        # backend can take several seconds to actually apply the change, so
        # an immediate re-poll consistently returns the OLD value and
        # overwrites this correct optimistic write with stale data. The
        # normal scheduled poll (Statistics Poll Interval) picks up the
        # confirmed real value once the backend has caught up.
        if self.coordinator.data is not None:
            self.coordinator.async_set_updated_data(
                {
                    **self.coordinator.data,
                    "smartshift_enabled": enabled,
                    "smartshift_off_source": "manual" if not enabled else None,
                }
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)


class AmberManualOverrideSwitch(AmberEntity, SwitchEntity):
    """Turns a specific manual battery override on or off.

    Turning on applies that override for the duration set on the paired
    "Manual Toggle Duration" number entity. Because only one override can be
    active at a time, this implicitly cancels whichever was active before -
    the other three switches will show off immediately, not just after the
    next poll.

    Turning off the switch that is currently active cancels the override,
    returning control to the Smart Shift plan. Turning off a switch that
    isn't the active one is a no-op - there's nothing on Amber's side to
    cancel.

    When the override's duration naturally expires, the next poll reports no
    active override and this switch shows off on its own - no separate
    "cancel" control is needed.
    """

    def __init__(
        self,
        coordinator: AmberStatsCoordinator,
        key: str,
        name: str,
        icon: str,
        override_value: str,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_icon = icon
        self._override_value = override_value

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("override_value") == self._override_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            result = await self.coordinator.api.async_set_override(
                self.coordinator.executor,
                self._override_value,
                self.coordinator.override_duration_minutes,
                source="manual",
            )
        except (AmberApiError, AmberAuthError) as err:
            raise HomeAssistantError(f"Amber override failed: {err}") from err

        # Deliberately NOT calling async_request_refresh() here - see the
        # module docstring. An immediate re-poll right after applying an
        # override consistently returns Amber's PRE-override state (their
        # backend has a real propagation delay), which would overwrite this
        # correct optimistic write with "no override" for one poll cycle.
        if self.coordinator.data is not None:
            updated = {
                **self.coordinator.data,
                "override_value": self._override_value,
                "override_source": "manual",
            }
            if result:
                # A new override was genuinely just applied - result is
                # None on a continuity-skip (same override already running
                # with time left, see async_set_override), in which case
                # the existing override_ends from the last real poll is
                # still accurate and must NOT be overwritten here, since a
                # fresh "duration from now" estimate would show MORE time
                # remaining than is actually left.
                #
                # Prefer Amber's own validTo. Self-consume overrides
                # specifically have been seen returning an empty one, in
                # which case this estimates from the duration just
                # requested instead - close, if not exact, and gets
                # corrected to Amber's authoritative value on the next
                # real poll regardless. Without this, the dashboard's
                # countdown line shows the action label immediately but no
                # time remaining until that next poll happens, which can
                # be tens of seconds away depending on the Statistics Poll
                # Interval.
                updated["override_ends"] = result.get("validTo") or (
                    datetime.now(timezone.utc)
                    + timedelta(minutes=self.coordinator.override_duration_minutes)
                ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                # Amber ignores overrides while Smart Shift is off, so
                # applying one auto-enables it (see api.py). Reflect that
                # here too, or the Smart Shift toggle would keep showing
                # off until the next poll even though it's actually on now.
                if result.get("_smartshift_was_enabled"):
                    updated["smartshift_enabled"] = True
            self.coordinator.async_set_updated_data(updated)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if not self.is_on:
            return

        try:
            await self.coordinator.api.async_cancel_override(self.coordinator.executor)
        except (AmberApiError, AmberAuthError) as err:
            raise HomeAssistantError(f"Cancel override failed: {err}") from err

        # Same reasoning as async_turn_on() - no immediate refresh, the
        # optimistic write is already correct.
        if self.coordinator.data is not None:
            self.coordinator.async_set_updated_data(
                {**self.coordinator.data, "override_value": None, "override_source": None}
            )


class AmberAutomationEnableSwitch(AmberEntity, SwitchEntity, RestoreEntity):
    """On/off switch for one of the Part 2 automation blueprints.

    Purely a stored flag - this integration never reads it. The blueprints
    check it as a condition, so turning it off stops that automation acting
    without having to delete it.

    Restores across restarts, so a restart doesn't silently re-enable an
    automation you'd turned off (or vice versa).
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: AmberStatsCoordinator,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_icon = icon
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._is_on = last.state == "on"

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self.async_write_ha_state()
