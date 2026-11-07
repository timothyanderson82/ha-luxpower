"""LuxPower inverters, read straight from the Wi-Fi dongle."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .client import LuxClient
from .const import ATTR_CONFIG_ENTRY_ID, CONF_DATALOG, DOMAIN, SERVICE_REFRESH
from .coordinator import LuxConfigEntry, LuxCoordinator

PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH, Platform.TIME]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def refresh(call: ServiceCall) -> None:
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        entries: list[LuxConfigEntry] = [
            entry
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            if entry_id in (None, entry.entry_id)
        ]
        if entry_id and not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        for entry in entries:
            if entry.state is ConfigEntryState.LOADED:
                await entry.runtime_data.async_refresh_all()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=REFRESH_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LuxConfigEntry) -> bool:
    client = LuxClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_DATALOG],
        entry.unique_id,
    )
    coordinator = LuxCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.close()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LuxConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.close()
    return unloaded
