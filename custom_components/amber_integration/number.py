"""Number entities for the Amber Electric Custom integration.

Two kinds live here:

  - Manual Toggle Duration, which belongs to Part 1 proper: how long a
    manual override switch holds for once turned on.

  - The Part 2 automation rule settings - three Sell rules and three Buy
    rules, each a battery level plus a price threshold. These only mean
    anything if you've set up the automation blueprints; on a Part-1-only
    install they sit inert in the Configuration section. They live here
    because a blueprint cannot create helpers, so anything an automation
    needs to reference has to exist as a real entity first.

Which rule applies at any moment is decided by the blueprints from the
battery level itself, not by rule number - see auto_sell.yaml/auto_buy.yaml.
Nothing here needs to know about that; these are just stored values.

All of them restore their value across restarts via RestoreEntity. Without
that a restart would silently reset a carefully-tuned price threshold back
to the default, which is the kind of thing you'd only notice from an
unexpected bill.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DEFAULT_BUY_RULE_1_BATTERY,
    DEFAULT_BUY_RULE_1_PRICE,
    DEFAULT_BUY_RULE_2_BATTERY,
    DEFAULT_BUY_RULE_2_PRICE,
    DEFAULT_BUY_RULE_3_BATTERY,
    DEFAULT_BUY_RULE_3_PRICE,
    DEFAULT_SELL_RULE_1_BATTERY,
    DEFAULT_SELL_RULE_1_PRICE,
    DEFAULT_SELL_RULE_2_BATTERY,
    DEFAULT_SELL_RULE_2_PRICE,
    DEFAULT_SELL_RULE_3_BATTERY,
    DEFAULT_SELL_RULE_3_PRICE,
    DOMAIN,
    MAX_BUY_PRICE_BOUND,
    MAX_SELL_PRICE_BOUND,
    MIN_BUY_PRICE_BOUND,
    MIN_SELL_PRICE_BOUND,
)
from .coordinator import AmberRuntimeData, AmberStatsCoordinator
from .entity import AmberEntity


@dataclass(frozen=True, kw_only=True)
class AmberNumberDescription(NumberEntityDescription):
    """Describes an Amber number entity."""

    default: float


AUTOMATION_NUMBERS: tuple[AmberNumberDescription, ...] = (
    # Sell Rule 1
    AmberNumberDescription(
        key="sell_rule_1_battery",
        name="Sell Rule 1 Battery Above",
        icon="mdi:battery-high",
        native_min_value=0, native_max_value=100, native_step=1,
        native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_SELL_RULE_1_BATTERY,
    ),
    AmberNumberDescription(
        key="sell_rule_1_price",
        name="Sell Rule 1 Min Price",
        icon="mdi:cash-plus",
        native_min_value=MIN_SELL_PRICE_BOUND, native_max_value=MAX_SELL_PRICE_BOUND,
        native_step=0.01, native_unit_of_measurement="$/kWh", mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_SELL_RULE_1_PRICE,
    ),
    # Sell Rule 2
    AmberNumberDescription(
        key="sell_rule_2_battery",
        name="Sell Rule 2 Battery Above",
        icon="mdi:battery-70",
        native_min_value=0, native_max_value=100, native_step=1,
        native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_SELL_RULE_2_BATTERY,
    ),
    AmberNumberDescription(
        key="sell_rule_2_price",
        name="Sell Rule 2 Min Price",
        icon="mdi:cash-plus",
        native_min_value=MIN_SELL_PRICE_BOUND, native_max_value=MAX_SELL_PRICE_BOUND,
        native_step=0.01, native_unit_of_measurement="$/kWh", mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_SELL_RULE_2_PRICE,
    ),
    # Sell Rule 3
    AmberNumberDescription(
        key="sell_rule_3_battery",
        name="Sell Rule 3 Battery Above",
        icon="mdi:battery-low",
        native_min_value=0, native_max_value=100, native_step=1,
        native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_SELL_RULE_3_BATTERY,
    ),
    AmberNumberDescription(
        key="sell_rule_3_price",
        name="Sell Rule 3 Min Price",
        icon="mdi:cash-plus",
        native_min_value=MIN_SELL_PRICE_BOUND, native_max_value=MAX_SELL_PRICE_BOUND,
        native_step=0.01, native_unit_of_measurement="$/kWh", mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_SELL_RULE_3_PRICE,
    ),
    # Buy Rule 1
    AmberNumberDescription(
        key="buy_rule_1_battery",
        name="Buy Rule 1 Battery Below",
        icon="mdi:battery-low",
        native_min_value=0, native_max_value=100, native_step=1,
        native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_BUY_RULE_1_BATTERY,
    ),
    AmberNumberDescription(
        key="buy_rule_1_price",
        name="Buy Rule 1 Max Price",
        icon="mdi:cash-minus",
        native_min_value=MIN_BUY_PRICE_BOUND, native_max_value=MAX_BUY_PRICE_BOUND,
        native_step=0.01, native_unit_of_measurement="$/kWh", mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_BUY_RULE_1_PRICE,
    ),
    # Buy Rule 2
    AmberNumberDescription(
        key="buy_rule_2_battery",
        name="Buy Rule 2 Battery Below",
        icon="mdi:battery-70",
        native_min_value=0, native_max_value=100, native_step=1,
        native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_BUY_RULE_2_BATTERY,
    ),
    AmberNumberDescription(
        key="buy_rule_2_price",
        name="Buy Rule 2 Max Price",
        icon="mdi:cash-minus",
        native_min_value=MIN_BUY_PRICE_BOUND, native_max_value=MAX_BUY_PRICE_BOUND,
        native_step=0.01, native_unit_of_measurement="$/kWh", mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_BUY_RULE_2_PRICE,
    ),
    # Buy Rule 3
    AmberNumberDescription(
        key="buy_rule_3_battery",
        name="Buy Rule 3 Battery Below",
        icon="mdi:battery-high",
        native_min_value=0, native_max_value=100, native_step=1,
        native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_BUY_RULE_3_BATTERY,
    ),
    AmberNumberDescription(
        key="buy_rule_3_price",
        name="Buy Rule 3 Max Price",
        icon="mdi:cash-minus",
        native_min_value=MIN_BUY_PRICE_BOUND, native_max_value=MAX_BUY_PRICE_BOUND,
        native_step=0.01, native_unit_of_measurement="$/kWh", mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        default=DEFAULT_BUY_RULE_3_PRICE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the duration control and the automation thresholds."""
    data: AmberRuntimeData = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = [AmberManualToggleDurationNumber(data.stats)]
    entities.extend(
        AmberAutomationNumber(data.stats, description)
        for description in AUTOMATION_NUMBERS
    )
    async_add_entities(entities)


class _AmberRestoringNumber(AmberEntity, NumberEntity, RestoreEntity):
    """Base for numbers that restore their value across a restart.

    Subclasses only say WHERE the value lives (_store_value / native_value);
    the guard-and-parse of the restored state is handled once here. Keeping
    it in one place matters because the guard has three separate failure
    modes to get right - no previous state at all, a state of "unknown" or
    "unavailable", and a state that won't parse as a number - and having
    that logic duplicated invites fixing one copy and not the other.
    """

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in ("unknown", "unavailable"):
            return
        try:
            self._store_value(float(last.state))
        except ValueError:
            pass

    def _store_value(self, value: float) -> None:
        """Write a value to wherever this entity keeps it."""
        raise NotImplementedError

    async def async_set_native_value(self, value: float) -> None:
        self._store_value(value)
        self.async_write_ha_state()


class AmberManualToggleDurationNumber(_AmberRestoringNumber):
    """Sets how long a manual override switch holds for once turned on.

    Lives on the coordinator rather than this entity, because the manual
    override switches read it when applying an override.
    """

    _attr_name = "Manual Toggle Duration"
    _attr_icon = "mdi:progress-clock"
    _attr_native_min_value = 5
    _attr_native_max_value = 240
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: AmberStatsCoordinator) -> None:
        super().__init__(coordinator, "manual_toggle_duration")

    def _store_value(self, value: float) -> None:
        # int() because it's a duration in whole minutes - the API takes an
        # integer, and a fractional minute would be silently truncated later
        # anyway.
        self.coordinator.override_duration_minutes = int(value)

    @property
    def native_value(self) -> float:
        return self.coordinator.override_duration_minutes


class AmberAutomationNumber(_AmberRestoringNumber):
    """A threshold used by the Part 2 automation blueprints.

    Holds its own value rather than reading from the coordinator - these are
    settings, not readings from Amber.
    """

    entity_description: AmberNumberDescription

    def __init__(
        self, coordinator: AmberStatsCoordinator, description: AmberNumberDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._value: float = description.default

    def _store_value(self, value: float) -> None:
        self._value = value

    @property
    def native_value(self) -> float:
        return self._value
