"""Percentage settings in the inverter's holding registers."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LuxConfigEntry, LuxCoordinator
from .entity import LuxEntity

# Writes go one at a time over the single dongle connection anyway
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class LuxNumberDescription(NumberEntityDescription):
    register: int
    legacy: str | None = None


def _percent(key: str, register: int, name: str, legacy: str | None = None, **kwargs):
    return LuxNumberDescription(
        key=key,
        register=register,
        name=name,
        legacy=legacy,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        **kwargs,
    )


NUMBERS = [
    _percent("charge_rate", 64, "System charge rate", "system_charge_rate"),
    _percent("discharge_rate", 65, "System discharge rate", "system_discharge_rate"),
    _percent("ac_charge_rate", 66, "AC charge rate"),
    _percent("ac_charge_soc_limit", 67, "AC charge SOC limit", "ac_charge_limit"),
    _percent("charge_priority_rate", 74, "Charge priority rate"),
    # Older lxp-bridge releases called register 75 "Forced Charge Limit"
    _percent("charge_priority_soc_limit", 75, "Charge priority SOC limit", "forced_charge_limit"),
    _percent(
        "forced_discharge_soc_limit", 83, "Forced discharge SOC limit", "forced_discharge_limit"
    ),
    _percent("discharge_cutoff_soc", 105, "Discharge cut-off SOC", "discharge_cutoff"),
    _percent(
        "eps_discharge_cutoff_soc", 125, "EPS discharge cut-off SOC", "discharge_cutoff_for_eps"
    ),
    _percent("ac_charge_start_soc", 160, "AC charge start SOC", "charge_from_ac_lower_limit"),
    _percent("ac_charge_end_soc", 161, "AC charge end SOC", "charge_from_ac_upper_limit"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(LuxNumber(coordinator, description) for description in NUMBERS)


class LuxNumber(LuxEntity, NumberEntity):
    """A percentage setting."""

    _platform_domain = "number"
    entity_description: LuxNumberDescription

    def __init__(self, coordinator: LuxCoordinator, description: LuxNumberDescription) -> None:
        super().__init__(coordinator, description, description.legacy)

    @property
    def available(self) -> bool:
        return (
            super().available and self.entity_description.register in self.coordinator.data.holdings
        )

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.holdings.get(self.entity_description.register)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write(self.entity_description.register, round(value))
