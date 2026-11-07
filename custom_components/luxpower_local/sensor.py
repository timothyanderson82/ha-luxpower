"""Readings from the inverter's input registers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LuxConfigEntry, LuxCoordinator
from .entity import LuxEntity
from .registers import FAULTS, WARNINGS, code_text, status_text

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LuxSensorDescription(SensorEntityDescription):
    """A sensor; ``legacy`` is the lxp-bridge object ID after ``lxp_<datalog>_``."""

    legacy: str | None = None
    bms: bool = False
    value_fn: Callable[[float | int], str | float | int] | None = None


VOLTAGE = LuxSensorDescription(
    key="",
    device_class=SensorDeviceClass.VOLTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfElectricPotential.VOLT,
)
CURRENT = LuxSensorDescription(
    key="",
    device_class=SensorDeviceClass.CURRENT,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
)
FREQUENCY = LuxSensorDescription(
    key="",
    device_class=SensorDeviceClass.FREQUENCY,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfFrequency.HERTZ,
)
POWER = LuxSensorDescription(
    key="",
    device_class=SensorDeviceClass.POWER,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfPower.WATT,
)
ENERGY = LuxSensorDescription(
    key="",
    device_class=SensorDeviceClass.ENERGY,
    state_class=SensorStateClass.TOTAL_INCREASING,
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
)
TEMPERATURE = LuxSensorDescription(
    key="",
    device_class=SensorDeviceClass.TEMPERATURE,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
)
DIAGNOSTIC = {"entity_category": EntityCategory.DIAGNOSTIC}


def _like(base: LuxSensorDescription, key: str, name: str, **kwargs) -> LuxSensorDescription:
    return replace(base, key=key, name=name, **kwargs)


def _pv_strings(base, key, name, legacy, **kwargs):
    return [
        _like(base, f"{key}_{n}", f"{name} string {n}", legacy=f"{legacy}_string_{n}", **kwargs)
        for n in (1, 2, 3)
    ]


SENSORS: list[LuxSensorDescription] = [
    LuxSensorDescription(
        key="status", name="Status", legacy="status", value_fn=status_text, icon="mdi:solar-power"
    ),
    LuxSensorDescription(
        key="soc",
        name="State of charge",
        legacy="state_of_charge",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    LuxSensorDescription(
        key="soh",
        name="State of health",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery-heart-variant",
        **DIAGNOSTIC,
    ),
    LuxSensorDescription(
        key="fault_code",
        name="Fault code",
        legacy="fault_code",
        value_fn=lambda v: code_text(int(v), FAULTS, "E"),
        icon="mdi:alert",
        **DIAGNOSTIC,
    ),
    LuxSensorDescription(
        key="warning_code",
        name="Warning code",
        legacy="warning_code",
        value_fn=lambda v: code_text(int(v), WARNINGS, "W"),
        icon="mdi:alert-outline",
        **DIAGNOSTIC,
    ),
    # Voltages and frequencies
    _like(VOLTAGE, "v_bat", "Battery voltage", legacy="battery_voltage"),
    _like(VOLTAGE, "v_ac_r", "Grid voltage", legacy="grid_voltage"),
    *_pv_strings(VOLTAGE, "v_pv", "PV voltage", "pv_voltage"),
    _like(VOLTAGE, "v_eps_r", "EPS voltage", legacy="eps_voltage"),
    _like(VOLTAGE, "v_bus_1", "Bus 1 voltage", entity_registry_enabled_default=False, **DIAGNOSTIC),
    _like(VOLTAGE, "v_bus_2", "Bus 2 voltage", entity_registry_enabled_default=False, **DIAGNOSTIC),
    _like(FREQUENCY, "f_ac", "Grid frequency", legacy="grid_frequency"),
    _like(FREQUENCY, "f_eps", "EPS frequency", legacy="eps_frequency"),
    LuxSensorDescription(
        key="pf",
        name="Power factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        **DIAGNOSTIC,
    ),
    # Power
    _like(POWER, "p_pv", "PV power", legacy="pv_power_array"),
    *_pv_strings(POWER, "p_pv", "PV power", "pv_power"),
    _like(POWER, "p_battery", "Battery power", legacy="battery_power_discharge_is_negative"),
    _like(POWER, "p_charge", "Battery charge power", legacy="battery_charge"),
    _like(POWER, "p_discharge", "Battery discharge power", legacy="battery_discharge"),
    _like(POWER, "p_grid", "Grid power", legacy="grid_power_export_is_negative"),
    _like(POWER, "p_to_user", "Power from grid", legacy="power_from_grid"),
    _like(POWER, "p_to_grid", "Power to grid", legacy="power_to_grid"),
    _like(POWER, "p_eps", "EPS power", legacy="active_eps_power"),
    LuxSensorDescription(
        key="s_eps",
        name="EPS apparent power",
        legacy="apparent_eps_power",
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
    ),
    _like(POWER, "p_inv", "Inverter power", legacy="inverter_power"),
    _like(POWER, "p_rec", "AC charge power", legacy="ac_charge_power"),
    # Energy today
    _like(ENERGY, "e_pv_day", "PV generation today", legacy="pv_generation_today"),
    *_pv_strings(ENERGY, "e_pv_day", "PV generation today", "pv_generation_today"),
    _like(ENERGY, "e_chg_day", "Battery charge today", legacy="battery_charge_today"),
    _like(ENERGY, "e_dischg_day", "Battery discharge today", legacy="battery_discharge_today"),
    _like(ENERGY, "e_to_user_day", "Energy from grid today", legacy="energy_from_grid_today"),
    _like(ENERGY, "e_to_grid_day", "Energy to grid today", legacy="energy_to_grid_today"),
    _like(ENERGY, "e_eps_day", "EPS energy today", legacy="energy_from_eps_today"),
    _like(ENERGY, "e_rec_day", "AC charge energy today", legacy="energy_of_ac_charging_today"),
    _like(ENERGY, "e_inv_day", "Inverter energy today", legacy="energy_of_inverter_today"),
    # Energy, lifetime
    _like(ENERGY, "e_pv_all", "PV generation total", legacy="pv_generation_all_time"),
    *_pv_strings(ENERGY, "e_pv_all", "PV generation total", "pv_generation_all_time"),
    _like(ENERGY, "e_chg_all", "Battery charge total", legacy="battery_charge_all_time"),
    _like(ENERGY, "e_dischg_all", "Battery discharge total", legacy="battery_discharge_all_time"),
    _like(ENERGY, "e_to_user_all", "Energy from grid total", legacy="energy_from_grid_all_time"),
    _like(ENERGY, "e_to_grid_all", "Energy to grid total", legacy="energy_to_grid_all_time"),
    _like(ENERGY, "e_eps_all", "EPS energy total", legacy="energy_from_eps_all_time"),
    _like(ENERGY, "e_rec_all", "AC charge energy total", legacy="energy_of_ac_charging_all_time"),
    _like(ENERGY, "e_inv_all", "Inverter energy total", legacy="energy_of_inverter_all_time"),
    # Temperatures
    _like(TEMPERATURE, "t_inner", "Inverter temperature", legacy="inverter_temperature"),
    _like(TEMPERATURE, "t_rad_1", "Radiator 1 temperature", legacy="radiator_1_temperature"),
    _like(TEMPERATURE, "t_rad_2", "Radiator 2 temperature", legacy="radiator_2_temperature"),
    _like(TEMPERATURE, "t_bat", "Battery temperature", legacy="battery_temperature"),
    LuxSensorDescription(
        key="runtime",
        name="Total runtime",
        legacy="total_runtime",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        **DIAGNOSTIC,
    ),
    # From the battery's BMS
    _like(CURRENT, "max_chg_curr", "Max charge current", legacy="max_charge_current", bms=True),
    _like(
        CURRENT,
        "max_dischg_curr",
        "Max discharge current",
        legacy="max_discharge_current",
        bms=True,
    ),
    _like(CURRENT, "bat_current", "Battery current", bms=True),
    _like(VOLTAGE, "charge_volt_ref", "Charge voltage", bms=True, **DIAGNOSTIC),
    _like(VOLTAGE, "dischg_cut_volt", "Discharge cut-off voltage", bms=True, **DIAGNOSTIC),
    _like(VOLTAGE, "vbat_inv", "Battery voltage (BMS)", bms=True, **DIAGNOSTIC),
    _like(
        VOLTAGE,
        "max_cell_voltage",
        "Max cell voltage",
        bms=True,
        suggested_display_precision=3,
    ),
    _like(
        VOLTAGE,
        "min_cell_voltage",
        "Min cell voltage",
        bms=True,
        suggested_display_precision=3,
    ),
    _like(TEMPERATURE, "max_cell_temp", "Max cell temperature", bms=True),
    _like(TEMPERATURE, "min_cell_temp", "Min cell temperature", bms=True),
    LuxSensorDescription(
        key="bat_capacity",
        name="Battery capacity",
        native_unit_of_measurement="Ah",
        icon="mdi:battery",
        bms=True,
        **DIAGNOSTIC,
    ),
    LuxSensorDescription(
        key="bat_count", name="Battery count", icon="mdi:battery-plus", bms=True, **DIAGNOSTIC
    ),
    LuxSensorDescription(
        key="cycle_count",
        name="Battery cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-sync",
        bms=True,
        **DIAGNOSTIC,
    ),
    LuxSensorDescription(
        key="bms_fault", name="BMS fault", icon="mdi:alert", bms=True, **DIAGNOSTIC
    ),
    LuxSensorDescription(
        key="bms_warning", name="BMS warning", icon="mdi:alert-outline", bms=True, **DIAGNOSTIC
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        LuxSensor(coordinator, description)
        for description in SENSORS
        if coordinator.read_bms or not description.bms
    )


class LuxSensor(LuxEntity, SensorEntity):
    """A reading from the inverter."""

    _platform_domain = "sensor"
    entity_description: LuxSensorDescription

    def __init__(self, coordinator: LuxCoordinator, description: LuxSensorDescription) -> None:
        super().__init__(coordinator, description, description.legacy)

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.key in self.coordinator.data.inputs

    @property
    def native_value(self) -> str | float | int | None:
        value = self.coordinator.data.inputs.get(self.entity_description.key)
        if value is None or self.entity_description.value_fn is None:
            return value
        return self.entity_description.value_fn(value)
