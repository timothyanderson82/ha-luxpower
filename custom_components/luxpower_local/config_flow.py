"""Set up a LuxPower inverter by its dongle's address and serial."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .client import LuxClient, LuxError
from .const import (
    CONF_DATALOG,
    CONF_HOLDING_INTERVAL,
    CONF_LEGACY_IDS,
    CONF_READ_BMS,
    CONF_SCAN_INTERVAL,
    DEFAULT_HOLDING_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_HOLDING_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_HOLDING_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .legacy import legacy_entity_ids
from .protocol import SERIAL_LEN

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "LuxPower inverter"


class CannotConnect(Exception):
    """The dongle did not answer."""


async def _probe(host: str, port: int, datalog: str) -> str:
    """Read the first input block and return the inverter serial it reports."""
    client = LuxClient(host, port, datalog)
    try:
        await client.read_inputs(0, 1)
    except LuxError as err:
        raise CannotConnect from err
    finally:
        await client.close()
    if not client.inverter:
        raise CannotConnect
    return client.inverter


def _connection_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_DATALOG, default=defaults.get(CONF_DATALOG, vol.UNDEFINED)): str,
        }
    )


class LuxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for LuxPower Local."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"entities": ""}
        if user_input is not None:
            datalog = user_input[CONF_DATALOG].strip().upper()
            if len(datalog) != SERIAL_LEN:
                errors[CONF_DATALOG] = "invalid_serial"
            else:
                try:
                    serial = await _probe(user_input[CONF_HOST], user_input[CONF_PORT], datalog)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(serial)
                    self._abort_if_unique_id_configured()
                    if user_input[CONF_LEGACY_IDS] and (taken := self._taken_ids(datalog)):
                        errors["base"] = "legacy_ids_taken"
                        placeholders["entities"] = ", ".join(taken[:3])
                    else:
                        return self.async_create_entry(
                            title=user_input[CONF_NAME],
                            data={
                                CONF_HOST: user_input[CONF_HOST],
                                CONF_PORT: user_input[CONF_PORT],
                                CONF_DATALOG: datalog,
                                CONF_LEGACY_IDS: user_input[CONF_LEGACY_IDS],
                            },
                        )

        defaults = user_input or {}
        schema = _connection_schema(defaults).extend(
            {
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
                vol.Required(CONF_LEGACY_IDS, default=defaults.get(CONF_LEGACY_IDS, False)): bool,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    def _taken_ids(self, datalog: str) -> list[str]:
        """lxp-bridge entity IDs still in use, which would push ours to ``_2``."""
        registry = er.async_get(self.hass)
        return [
            entity_id
            for entity_id in legacy_entity_ids(datalog)
            if registry.async_get(entity_id) or self.hass.states.get(entity_id)
        ]

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            datalog = user_input[CONF_DATALOG].strip().upper()
            try:
                serial = await _probe(user_input[CONF_HOST], user_input[CONF_PORT], datalog)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_mismatch(reason="wrong_inverter")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_DATALOG: datalog,
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or dict(entry.data)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LuxOptionsFlow:
        return LuxOptionsFlow()


def _seconds(minimum: int, maximum: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


class LuxOptionsFlow(OptionsFlowWithReload):
    """How often to poll, and whether to read the BMS block."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_HOLDING_INTERVAL: int(user_input[CONF_HOLDING_INTERVAL]),
                    CONF_READ_BMS: user_input[CONF_READ_BMS],
                }
            )
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): _seconds(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL),
                vol.Required(
                    CONF_HOLDING_INTERVAL,
                    default=options.get(CONF_HOLDING_INTERVAL, DEFAULT_HOLDING_INTERVAL),
                ): _seconds(MIN_HOLDING_INTERVAL, MAX_HOLDING_INTERVAL),
                vol.Required(CONF_READ_BMS, default=options.get(CONF_READ_BMS, True)): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
