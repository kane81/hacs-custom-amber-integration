"""Shared entity base for the Amber Electric Custom integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AmberPriceCoordinator, AmberStatsCoordinator

AmberCoordinatorType = AmberStatsCoordinator | AmberPriceCoordinator


class AmberEntity(CoordinatorEntity[AmberCoordinatorType]):
    """Base entity, groups everything under one Amber device.

    Works with either coordinator - entities pick whichever one their data
    actually comes from (see AmberRuntimeData in coordinator.py). Both
    coordinator types share the same .entry attribute, which is all this
    base class needs.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: AmberCoordinatorType, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Amber Smart Shift",
            manufacturer="Amber Electric",
            model="Smart Shift",
            configuration_url="https://app.amber.com.au",
        )
