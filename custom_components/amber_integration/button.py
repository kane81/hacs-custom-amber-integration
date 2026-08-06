"""Force refresh button for the Amber Electric Custom integration.

A manual "check now" button, distinct from the manual override switches -
this doesn't correspond to a persistent on/off state, it's a one-shot action,
which is exactly what HA's button platform is for.

No settle delay before polling here, unlike the settle-delay added to the
override services (__init__.py) - this button is for genuinely checking the
current state on demand, not confirming a mutation this integration just
made. If someone presses it right after changing something in the Amber app
directly, they want to see whatever Amber's backend currently reports, not
a deliberately-stale read.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AmberPriceCoordinator, AmberRuntimeData, AmberStatsCoordinator
from .entity import AmberEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the force refresh button."""
    data: AmberRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AmberForceRefreshButton(data.stats, data.price)])


class AmberForceRefreshButton(AmberEntity, ButtonEntity):
    """Polls both coordinators immediately on press."""

    _attr_name = "Force Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(
        self, stats: AmberStatsCoordinator, price: AmberPriceCoordinator
    ) -> None:
        # Attached to the stats coordinator for device grouping purposes,
        # like every other entity - but presses refresh both, since this
        # button isn't specific to either data domain.
        super().__init__(stats, "force_refresh")
        self._price_coordinator = price

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
        await self._price_coordinator.async_request_refresh()
