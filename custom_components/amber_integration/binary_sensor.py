"""Binary sensors for the Amber Electric Custom integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AmberRuntimeData, AmberStatsCoordinator
from .entity import AmberEntity


@dataclass(frozen=True, kw_only=True)
class AmberBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Amber binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[AmberBinarySensorDescription, ...] = (
    AmberBinarySensorDescription(
        key="battery_connection",
        name="Battery Connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        # Amber returns a null SOC when it cannot reach the battery
        value_fn=lambda d: d.get("battery_online"),
    ),
    AmberBinarySensorDescription(
        key="manual_action",
        name="Manual Action",
        icon="mdi:hand-back-right",
        value_fn=lambda d: bool(d.get("override_value")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Amber binary sensors.

    Both come from the stats coordinator - battery_online and override_value
    are both stats-domain fields, not price ones.
    """
    data: AmberRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AmberBinarySensor(data.stats, description)
        for description in BINARY_SENSORS
    )


class AmberBinarySensor(AmberEntity, BinarySensorEntity):
    """A binary sensor backed by the coordinator data."""

    entity_description: AmberBinarySensorDescription

    def __init__(
        self, coordinator: AmberStatsCoordinator, description: AmberBinarySensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
