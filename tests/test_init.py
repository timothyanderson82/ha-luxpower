"""Setup, entities and writes, with a fake dongle on localhost."""

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.luxpower_local.const import (
    CONF_DATALOG,
    CONF_HOLDING_INTERVAL,
    CONF_LEGACY_IDS,
    CONF_READ_BMS,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.luxpower_local.protocol import DeviceFunction
from custom_components.luxpower_local.registers import AC_CHARGE_BIT, FORCED_DISCHARGE_BIT

from .conftest import DATALOG, SERIAL, FakeDongle

# The scan interval plus the coordinator's up-to-half-a-second jitter
POLL = timedelta(seconds=11)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, **options) -> None:
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let one scan interval pass; the coordinator refreshes in a background task."""
    freezer.tick(POLL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}")
    assert entity_id, key
    return entity_id


def _state(hass: HomeAssistant, platform: str, key: str) -> str:
    return hass.states.get(_entity_id(hass, platform, key)).state


async def test_setup_reads_everything(
    hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle
) -> None:
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    assert _state(hass, "sensor", "soc") == "90"
    assert _state(hass, "sensor", "p_grid") == "3790"
    assert _state(hass, "sensor", "e_pv_all") == "18836.9"
    assert _state(hass, "sensor", "status") == "PV & battery on-grid"
    assert _state(hass, "sensor", "fault_code") == "OK"
    assert _state(hass, "sensor", "min_cell_voltage") == "3.5"
    assert _state(hass, "number", "discharge_cutoff_soc") == "90"
    assert _state(hass, "switch", "ac_charge") == "on"
    assert _state(hass, "switch", "forced_discharge") == "off"
    assert _state(hass, "time", "ac_charge_1_end") == "23:59:00"

    reads = [(f, r) for f, r, _ in dongle.requests]
    assert reads == [(4, 0), (4, 40), (4, 80), (3, 0), (3, 40), (3, 80), (3, 120), (3, 160)]


async def test_lxp_bridge_entity_ids(hass: HomeAssistant, dongle: FakeDongle) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Inverter",
        unique_id=SERIAL,
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: dongle.port,
            CONF_DATALOG: DATALOG,
            CONF_LEGACY_IDS: True,
        },
    )
    await _setup(hass, entry)
    prefix = f"lxp_{DATALOG.lower()}"
    assert hass.states.get(f"sensor.{prefix}_pv_generation_all_time").state == "18836.9"
    assert hass.states.get(f"sensor.{prefix}_battery_charge_all_time").state == "1246.9"
    assert hass.states.get(f"sensor.{prefix}_battery_discharge_all_time").state == "680.2"
    assert hass.states.get(f"number.{prefix}_discharge_cutoff").state == "90"
    assert hass.states.get(f"switch.{prefix}_ac_charge").state == "on"
    # New entities with no lxp-bridge counterpart are named normally
    assert _entity_id(hass, "sensor", "soh") == "sensor.inverter_state_of_health"


async def test_bms_can_be_turned_off(
    hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle
) -> None:
    await _setup(hass, entry, **{CONF_READ_BMS: False})
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_min_cell_voltage") is None
    assert (DeviceFunction.READ_INPUT, 80, 40) not in dongle.requests


async def test_polls_inputs_often_and_settings_rarely(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    dongle: FakeDongle,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, entry, **{CONF_SCAN_INTERVAL: 10, CONF_HOLDING_INTERVAL: 60})
    dongle.requests.clear()

    dongle.inputs[5] = 98 << 8 | 91
    await _poll(hass, freezer)
    assert _state(hass, "sensor", "soc") == "91"
    assert {f for f, _, _ in dongle.requests} == {DeviceFunction.READ_INPUT}

    for _ in range(6):
        await _poll(hass, freezer)
    assert (DeviceFunction.READ_HOLD, 0, 40) in dongle.requests


async def test_tolerates_a_few_missed_polls(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    dongle: FakeDongle,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, entry)
    # Time is frozen, so reply timeouts never fire; drop the connection instead
    dongle.drop = True
    for missed in range(1, 4):
        await _poll(hass, freezer)
        expected = STATE_UNAVAILABLE if missed == 3 else "90"
        assert _state(hass, "sensor", "soc") == expected, missed

    dongle.drop = False
    await _poll(hass, freezer)
    assert _state(hass, "sensor", "soc") == "90"


async def test_lifetime_energy_never_goes_backwards(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    dongle: FakeDongle,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, entry)
    # A bogus all-zero reading of the lifetime battery charge counter
    dongle.inputs[50] = dongle.inputs[51] = 0
    await _poll(hass, freezer)
    assert _state(hass, "sensor", "e_chg_all") == "1246.9"

    dongle.inputs[50] += 20000  # +2000.0 kWh in the low word
    await _poll(hass, freezer)
    assert float(_state(hass, "sensor", "e_chg_all")) == 2000.0


async def test_set_number(hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle) -> None:
    await _setup(hass, entry)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _entity_id(hass, "number", "discharge_cutoff_soc"), "value": 30},
        blocking=True,
    )
    assert dongle.holdings[105] == 30
    assert _state(hass, "number", "discharge_cutoff_soc") == "30"


async def test_switch_changes_only_its_bit(
    hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle
) -> None:
    await _setup(hass, entry)
    before = dongle.holdings[21]
    # Something else (the app) changes the register after our last read
    dongle.holdings[21] = before & ~AC_CHARGE_BIT
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": _entity_id(hass, "switch", "forced_discharge")},
        blocking=True,
    )
    assert dongle.holdings[21] == (before & ~AC_CHARGE_BIT) | FORCED_DISCHARGE_BIT
    assert _state(hass, "switch", "forced_discharge") == "on"
    assert _state(hass, "switch", "ac_charge") == "off"


async def test_set_time(hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle) -> None:
    await _setup(hass, entry)
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": _entity_id(hass, "time", "forced_discharge_1_start"), "time": "17:30:00"},
        blocking=True,
    )
    assert dongle.holdings[84] == 17 | 30 << 8


async def test_rejected_write_raises(
    hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle
) -> None:
    await _setup(hass, entry)
    dongle.reject.add(105)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": _entity_id(hass, "number", "discharge_cutoff_soc"), "value": 30},
            blocking=True,
        )
    assert _state(hass, "number", "discharge_cutoff_soc") == "90"


async def test_refresh_action_reads_settings(
    hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle
) -> None:
    await _setup(hass, entry)
    dongle.requests.clear()
    dongle.holdings[105] = 40
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert _state(hass, "number", "discharge_cutoff_soc") == "40"
    assert (DeviceFunction.READ_HOLD, 80, 40) in dongle.requests


async def test_not_ready_when_dongle_silent(
    hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle
) -> None:
    dongle.mute = True
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_closes_connection(
    hass: HomeAssistant, entry: MockConfigEntry, dongle: FakeDongle
) -> None:
    await _setup(hass, entry)
    client = entry.runtime_data.client
    assert client.connected
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not client.connected


async def test_adopts_lxp_bridge_ids_for_restored_entities(
    hass: HomeAssistant, dongle: FakeDongle
) -> None:
    """Re-adding an entry gives entities back their old IDs; setup moves them over."""
    registry = er.async_get(hass)
    prefix = f"lxp_{DATALOG.lower()}"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SNA5000",
        unique_id=SERIAL,
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: dongle.port,
            CONF_DATALOG: DATALOG,
            CONF_LEGACY_IDS: True,
        },
    )
    entry.add_to_hass(hass)
    # As restored from a deleted entry: friendly IDs, and runtime saved in hours
    pv = registry.async_get_or_create(
        "sensor", DOMAIN, f"{SERIAL}_e_pv_all", suggested_object_id="garage_sna5000_pv_total"
    )
    runtime = registry.async_get_or_create(
        "sensor", DOMAIN, f"{SERIAL}_runtime", suggested_object_id="garage_sna5000_total_runtime"
    )
    registry.async_update_entity_options(
        runtime.entity_id, "sensor.private", {"suggested_unit_of_measurement": "h"}
    )
    # The registry also remembers the unit the entity last reported
    registry.async_update_entity(runtime.entity_id, unit_of_measurement="h")
    # Something else holds one target ID: that entity is left alone
    registry.async_get_or_create("sensor", "other", "x", suggested_object_id=f"{prefix}_status")
    registry.async_get_or_create(
        "sensor", DOMAIN, f"{SERIAL}_status", suggested_object_id="garage_sna5000_status"
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(pv.entity_id) is None
    assert hass.states.get(f"sensor.{prefix}_pv_generation_all_time").state == "18836.9"
    runtime_state = hass.states.get(f"sensor.{prefix}_total_runtime")
    assert runtime_state.attributes["unit_of_measurement"] == "s"
    assert _entity_id(hass, "sensor", "status") == "sensor.garage_sna5000_status"
