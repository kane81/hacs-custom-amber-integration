"""Config flow for the Amber Electric Custom integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AmberApi, AmberApiError, AmberAuthError
from .const import (
    CONF_CONFIG_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_POWER_BATTERY_LEVEL_SENSOR,
    CONF_POWER_BATTERY_SENSOR,
    CONF_POWER_GRID_SENSOR,
    CONF_POWER_LOAD_SENSOR,
    CONF_POWER_SOLAR_SENSOR,
    CONF_PRICE_SCAN_INTERVAL,
    CONF_SITE_ID,
    CONF_STATS_SCAN_INTERVAL,
    DEFAULT_PRICE_SCAN_INTERVAL,
    DEFAULT_STATS_SCAN_INTERVAL,
    DOMAIN,
    MAX_PRICE_SCAN_INTERVAL,
    MAX_STATS_SCAN_INTERVAL,
    MIN_PRICE_SCAN_INTERVAL,
    MIN_STATS_SCAN_INTERVAL,
)

# All five optional - an entity selector with no vol.Required wrapper.
# power_domains restricts the picker to domains where a power/energy/soc
# reading would actually live, so the list isn't cluttered with switches,
# lights, and everything else in a typical install.
_POWER_SENSOR_FIELDS = {
    CONF_POWER_BATTERY_SENSOR: ["sensor"],
    CONF_POWER_BATTERY_LEVEL_SENSOR: ["sensor"],
    CONF_POWER_SOLAR_SENSOR: ["sensor"],
    CONF_POWER_LOAD_SENSOR: ["sensor"],
    CONF_POWER_GRID_SENSOR: ["sensor"],
}

STEP_POWER_SENSORS_SCHEMA = vol.Schema(
    {
        vol.Optional(key): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=domains)
        )
        for key, domains in _POWER_SENSOR_FIELDS.items()
    }
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class AmberConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Amber login prompt."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None
        # Holds email/password/site_id/config_id between async_step_user
        # succeeding and async_step_power_sensors finishing - the entry
        # isn't created until the power sensors step completes (or is
        # skipped), so this is where the already-validated data waits.
        self._pending_data: dict[str, Any] = {}

    async def _async_validate(self, email: str, password: str) -> dict[str, Any]:
        """Log in and discover the site and battery config IDs."""
        api = AmberApi(async_get_clientsession(self.hass), email, password)
        await api.async_authenticate(self.hass.async_add_executor_job)
        site_id, config_id = await api.async_discover_site(
            self.hass.async_add_executor_job
        )
        return {CONF_SITE_ID: site_id, CONF_CONFIG_ID: config_id}

    async def _async_try_validate(
        self, email: str, password: str
    ) -> tuple[dict[str, str] | None, str | None]:
        """Validate credentials, mapping any failure to an error key.

        Returns (discovered, None) on success or (None, error_key) on
        failure. Shared by the initial setup and reauth steps so both map
        the same exceptions to the same messages - reauth previously did
        not catch unexpected exceptions at all, so an unforeseen error
        there surfaced as a raw traceback rather than the "unknown"
        message that strings.json already defines.
        """
        try:
            return await self._async_validate(email, password), None
        except AmberAuthError:
            return None, "invalid_auth"
        except AmberApiError:
            return None, "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Amber credentials")
            return None, "unknown"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            discovered, error = await self._async_try_validate(email, password)
            if error:
                errors["base"] = error
            else:
                assert discovered is not None
                self._pending_data = {
                    CONF_EMAIL: email,
                    CONF_PASSWORD: password,
                    **discovered,
                }
                return await self.async_step_power_sensors()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_power_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Optional - point the dashboard's Power card at your own sensors.

        Every field is optional and all can be left blank. This is purely a
        convenience for filling them in now if you already know the entity
        IDs; skipping entirely and configuring them later, one at a time,
        under the integration's Configuration section works exactly the
        same - these are ordinary editable entities (text.py), this step
        only sets their starting value.
        """
        if user_input is not None:
            data = {**self._pending_data, **user_input}
            return self.async_create_entry(
                title=f"HA Custom Amber Electric Integration ({data[CONF_EMAIL]})",
                data=data,
                options={
                    CONF_STATS_SCAN_INTERVAL: DEFAULT_STATS_SCAN_INTERVAL,
                    CONF_PRICE_SCAN_INTERVAL: DEFAULT_PRICE_SCAN_INTERVAL,
                },
            )

        return self.async_show_form(
            step_id="power_sensors", data_schema=STEP_POWER_SENSORS_SCHEMA
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        if user_input is not None:
            email = self._reauth_entry.data[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            discovered, error = await self._async_try_validate(email, password)
            if error:
                errors["base"] = error
            else:
                assert discovered is not None
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_PASSWORD: password,
                        **discovered,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AmberOptionsFlow:
        return AmberOptionsFlow(config_entry)


class AmberOptionsFlow(config_entries.OptionsFlow):
    """Adjust the two poll intervals after setup.

    Stores the entry explicitly under self._entry rather than relying on
    self.config_entry - whether that's auto-populated by the framework or
    needs manual assignment differs across HA versions (newer versions
    auto-populate it as a read-only property and deprecate manual
    assignment; older versions require it). Storing it under a different
    name sidesteps that entirely rather than guessing which applies here.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_stats = self._entry.options.get(
            CONF_STATS_SCAN_INTERVAL, DEFAULT_STATS_SCAN_INTERVAL
        )
        current_price = self._entry.options.get(
            CONF_PRICE_SCAN_INTERVAL, DEFAULT_PRICE_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_STATS_SCAN_INTERVAL, default=current_stats
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_STATS_SCAN_INTERVAL, max=MAX_STATS_SCAN_INTERVAL
                        ),
                    ),
                    vol.Required(
                        CONF_PRICE_SCAN_INTERVAL, default=current_price
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_PRICE_SCAN_INTERVAL, max=MAX_PRICE_SCAN_INTERVAL
                        ),
                    ),
                }
            ),
        )
