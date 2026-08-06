"""Power sensor configuration for the Amber Electric Custom integration.

Five text entities, each holding the entity_id of one of YOUR OWN existing
sensors - battery power, an optional battery level override, solar, load,
and grid. This integration has no way to know what solar/inverter setup you
have, so rather than trying to auto-detect anything, you tell it which of
your own entities to read by pasting the entity_id in.

All five default to empty and are entirely optional - the dashboard's Power
card only shows a row for a sensor that's actually configured, and doesn't
show the card at all if none of the four power readings are set (battery
level alone doesn't count, since it's only a detail attached to the battery
row - see below).

This is a plain text box, not a dropdown picker - Home Assistant doesn't
have a persistent "entity picker" entity type the way blueprints and config
flows do with their entity selectors, only one-time-flow inputs get that.
You'll need to know or copy the exact entity_id.

Values restore across restarts via RestoreEntity, same as the automation
rule thresholds - this is a one-time setup, not something that should reset
itself on every reboot.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_POWER_BATTERY_LEVEL_SENSOR,
    CONF_POWER_BATTERY_SENSOR,
    CONF_POWER_GRID_SENSOR,
    CONF_POWER_LOAD_SENSOR,
    CONF_POWER_SOLAR_SENSOR,
    DOMAIN,
)
from .coordinator import AmberRuntimeData, AmberStatsCoordinator
from .entity import AmberEntity


@dataclass(frozen=True, kw_only=True)
class AmberTextDescription(TextEntityDescription):
    """Describes an Amber text entity."""


POWER_SENSORS: tuple[AmberTextDescription, ...] = (
    AmberTextDescription(
        key=CONF_POWER_BATTERY_SENSOR,
        name="Power: Battery Sensor",
        icon="mdi:battery-sync",
        entity_category=EntityCategory.CONFIG,
    ),
    AmberTextDescription(
        key=CONF_POWER_BATTERY_LEVEL_SENSOR,
        name="Power: Battery Level Sensor",
        icon="mdi:battery-heart-variant",
        entity_category=EntityCategory.CONFIG,
    ),
    AmberTextDescription(
        key=CONF_POWER_SOLAR_SENSOR,
        name="Power: Solar Sensor",
        icon="mdi:solar-power",
        entity_category=EntityCategory.CONFIG,
    ),
    AmberTextDescription(
        key=CONF_POWER_LOAD_SENSOR,
        name="Power: Load Sensor",
        icon="mdi:home-lightning-bolt",
        entity_category=EntityCategory.CONFIG,
    ),
    AmberTextDescription(
        key=CONF_POWER_GRID_SENSOR,
        name="Power: Grid Sensor",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Power sensor configuration entities."""
    data: AmberRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AmberPowerSensorText(data.stats, description) for description in POWER_SENSORS
    )


class AmberPowerSensorText(AmberEntity, TextEntity, RestoreEntity):
    """Holds the entity_id of one of your own sensors for the Power card.

    Not a reading itself - the value stored here IS an entity_id, read a
    second time by the dashboard to get the actual number
    (states(states('text.this_entity'))). Empty by default; the dashboard
    treats empty the same as "not configured".

    On first creation, seeded from whatever was entered (or left blank) on
    the optional Power sensors step during setup - see config_flow.py.
    That's only ever the STARTING value though: if RestoreEntity finds a
    later state from you editing this entity directly, that wins instead,
    same as every other restoring entity in this integration. The seed
    only matters the very first time this entity is ever created.
    """

    entity_description: AmberTextDescription
    _attr_mode = TextMode.TEXT
    _attr_native_max = 255

    def __init__(
        self, coordinator: AmberStatsCoordinator, description: AmberTextDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._value: str = coordinator.entry.data.get(description.key, "")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            self._value = last.state

    @property
    def native_value(self) -> str:
        return self._value

    async def async_set_value(self, value: str) -> None:
        self._value = value.strip()
        self.async_write_ha_state()
