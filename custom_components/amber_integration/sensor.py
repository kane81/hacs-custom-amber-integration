"""Sensors for the Amber Electric Custom integration.

Split across the two coordinators - price/earnings sensors read from the
slow price coordinator, everything else (battery, override, market state)
reads from the fast stats coordinator. See coordinator.py for why.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import parse_amber_timestamp
from .const import DOMAIN
from .coordinator import AmberRuntimeData
from .entity import AmberCoordinatorType, AmberEntity


@dataclass(frozen=True, kw_only=True)
class AmberSensorDescription(SensorEntityDescription):
    """Describes an Amber sensor."""

    value_fn: Callable[[dict[str, Any]], Any]


PRICE_SENSORS: tuple[AmberSensorDescription, ...] = (
    AmberSensorDescription(
        key="buy_price",
        name="Buy Price",
        icon="mdi:transmission-tower-export",
        native_unit_of_measurement="$/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.get("buy_price"),
    ),
    AmberSensorDescription(
        key="sell_price",
        name="Sell Price",
        icon="mdi:transmission-tower-import",
        native_unit_of_measurement="$/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.get("sell_price"),
    ),
    AmberSensorDescription(
        key="import_cost",
        name="Current Import Cost",
        icon="mdi:cash-minus",
        native_unit_of_measurement="¢",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.get("import_cost"),
    ),
    AmberSensorDescription(
        key="export_earnings",
        name="Current Export Earnings",
        icon="mdi:cash-plus",
        native_unit_of_measurement="¢",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.get("export_earnings"),
    ),
    AmberSensorDescription(
        key="total_earnings",
        name="Current Net Earnings",
        icon="mdi:cash",
        native_unit_of_measurement="¢",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: d.get("total_earnings"),
    ),
)

STATS_SENSORS: tuple[AmberSensorDescription, ...] = (
    AmberSensorDescription(
        key="battery_soc",
        name="Battery Level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.get("soc"),
    ),
    AmberSensorDescription(
        key="battery_power",
        name="Battery Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.get("battery_power"),
    ),
    AmberSensorDescription(
        key="battery_capacity",
        name="Battery Capacity",
        icon="mdi:battery-high",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        # Total usable capacity, not current charge - see api.py's
        # async_get_stats for where this comes from (smartshift.plan(),
        # piggybacked onto the existing stats poll rather than a dedicated
        # query, since this value is effectively static). Genuinely useful
        # beyond this integration's own dashboard - anything doing its own
        # charge/discharge math (kWh needed to reach X%, time-to-full at a
        # given rate, and so on) needs this and has no other way to get it,
        # since it's not exposed by Amber's live() query at all.
        value_fn=lambda d: d.get("battery_capacity"),
    ),
    AmberSensorDescription(
        key="market_state",
        name="Market State",
        icon="mdi:battery-sync",
        value_fn=lambda d: d.get("power_state_description") or d.get("power_state"),
    ),
    AmberSensorDescription(
        key="current_manual_action",
        name="Current Manual Action",
        icon="mdi:hand-back-right",
        value_fn=lambda d: d.get("override_value") or "none",
    ),
    AmberSensorDescription(
        key="manual_action_ends",
        name="Manual Action Ends",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:timer-sand",
        value_fn=lambda d: parse_amber_timestamp(d.get("override_ends")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Amber sensors."""
    data: AmberRuntimeData = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        AmberSensor(data.price, description) for description in PRICE_SENSORS
    ]
    entities.extend(
        AmberSensor(data.stats, description) for description in STATS_SENSORS
    )
    entities.append(AmberLastPolledSensor(data.stats, "last_stats_poll", "Last Stats Poll"))
    entities.append(AmberLastPolledSensor(data.price, "last_price_poll", "Last Price Poll"))
    async_add_entities(entities)


class AmberSensor(AmberEntity, SensorEntity):
    """A sensor backed by whichever coordinator's data it needs."""

    entity_description: AmberSensorDescription

    # Sensors that expose the raw override fields as attributes, for
    # debugging why "Manual Action Ends" sometimes shows Unknown while an
    # override is genuinely active. Amber's schema has both validTo and a
    # separate estimatedEndDate on effectiveOverride - if self-consume
    # overrides populate one but not the other, this is how to see it
    # directly rather than guessing.
    _DIAGNOSTIC_KEYS = {"manual_action_ends", "current_manual_action"}

    def __init__(
        self, coordinator: AmberCoordinatorType, description: AmberSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._key not in self._DIAGNOSTIC_KEYS or not self.coordinator.data:
            return None
        d = self.coordinator.data
        return {
            "raw_override_id": d.get("override_id"),
            "raw_override_state": d.get("override_state"),
            # Already validTo-or-estimatedEndDate by the time it gets here
            # (see api.py) - this is what native_value's countdown is
            # actually parsing.
            "raw_override_ends": d.get("override_ends"),
            # Which caller applied the currently active override ("manual",
            # "auto_buy", "auto_sell", "service", or None if unknown/not
            # set by this integration). The auto_sell/auto_buy blueprints
            # check this before cancelling, so they only ever cancel an
            # override they applied themselves - not a manual toggle or
            # each other's.
            "source": d.get("override_source"),
        }


class AmberLastPolledSensor(AmberEntity, SensorEntity):
    """When the last successful poll completed, for one of the coordinators."""

    _attr_icon = "mdi:cloud-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: AmberCoordinatorType, key: str, name: str) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_success_time
