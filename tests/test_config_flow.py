"""Config, reconfigure and options flows."""

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.luxpower_local.const import (
    CONF_DATALOG,
    CONF_HOLDING_INTERVAL,
    CONF_LEGACY_IDS,
    CONF_READ_BMS,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import DATALOG, SERIAL, FakeDongle


def _user_input(dongle: FakeDongle, **overrides):
    return {
        CONF_HOST: "127.0.0.1",
        CONF_PORT: dongle.port,
        CONF_DATALOG: DATALOG.lower(),
        CONF_NAME: "LuxPower SNA5000",
        CONF_LEGACY_IDS: True,
        **overrides,
    }


async def test_user_flow_learns_serial(hass: HomeAssistant, dongle: FakeDongle) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input(dongle))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "LuxPower SNA5000"
    assert result["result"].unique_id == SERIAL
    assert result["data"] == {
        CONF_HOST: "127.0.0.1",
        CONF_PORT: dongle.port,
        CONF_DATALOG: DATALOG,
        CONF_LEGACY_IDS: True,
    }


async def test_user_flow_errors(hass: HomeAssistant, dongle: FakeDongle) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(dongle, **{CONF_DATALOG: "short"})
    )
    assert result["errors"] == {CONF_DATALOG: "invalid_serial"}

    dongle.mute = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input(dongle))
    assert result["errors"] == {"base": "cannot_connect"}

    dongle.mute = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input(dongle))
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_already_configured(
    hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle
) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input(dongle))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle) -> None:
    entry.add_to_hass(hass)
    moved = FakeDongle()
    await moved.start()
    try:
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "127.0.0.1", CONF_PORT: moved.port, CONF_DATALOG: DATALOG},
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_PORT] == moved.port
        assert entry.data[CONF_LEGACY_IDS] is False
        assert moved.connections
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await moved.stop()


async def test_options(hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 30, CONF_HOLDING_INTERVAL: 600, CONF_READ_BMS: False},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_SCAN_INTERVAL: 30,
        CONF_HOLDING_INTERVAL: 600,
        CONF_READ_BMS: False,
    }
    # Reloaded with the new interval
    assert entry.runtime_data.update_interval.total_seconds() == 30
    assert not entry.runtime_data.read_bms


async def test_legacy_ids_refused_while_lxp_bridge_entities_exist(
    hass: HomeAssistant, dongle: FakeDongle
) -> None:
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor",
        "mqtt",
        f"lxp_{DATALOG}_e_pv_all",
        suggested_object_id=f"lxp_{DATALOG.lower()}_pv_generation_all_time",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input(dongle))
    assert result["errors"] == {"base": "legacy_ids_taken"}
    assert old.entity_id in result["description_placeholders"]["entities"]

    registry.async_remove(old.entity_id)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input(dongle))
    assert result["type"] is FlowResultType.CREATE_ENTRY
