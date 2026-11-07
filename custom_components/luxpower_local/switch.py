"""On/off settings held as bits of holding register 21."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LuxConfigEntry, LuxCoordinator
from .entity import LuxEntity
from .registers import AC_CHARGE_BIT, CHARGE_PRIORITY_BIT, FORCED_DISCHARGE_BIT, REG_FUNCTIONS

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class LuxSwitchDescription(SwitchEntityDescription):
    bit: int
    legacy: str


SWITCHES = [
    LuxSwitchDescription(
        key="ac_charge",
        name="AC charge",
        bit=AC_CHARGE_BIT,
        legacy="ac_charge",
        icon="mdi:transmission-tower-import",
    ),
    LuxSwitchDescription(
        key="charge_priority",
        name="Charge priority",
        bit=CHARGE_PRIORITY_BIT,
        legacy="charge_priority",
        icon="mdi:battery-charging-high",
    ),
    LuxSwitchDescription(
        key="forced_discharge",
        name="Forced discharge",
        bit=FORCED_DISCHARGE_BIT,
        legacy="forced_discharge",
        icon="mdi:battery-arrow-down",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(LuxSwitch(coordinator, description) for description in SWITCHES)


class LuxSwitch(LuxEntity, SwitchEntity):
    """One bit of the inverter's function register."""

    _platform_domain = "switch"
    _attr_entity_category = EntityCategory.CONFIG
    entity_description: LuxSwitchDescription

    def __init__(self, coordinator: LuxCoordinator, description: LuxSwitchDescription) -> None:
        super().__init__(coordinator, description, description.legacy)

    @property
    def available(self) -> bool:
        return super().available and REG_FUNCTIONS in self.coordinator.data.holdings

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.holdings.get(REG_FUNCTIONS)
        return None if value is None else bool(value & self.entity_description.bit)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_bit(REG_FUNCTIONS, self.entity_description.bit, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_bit(REG_FUNCTIONS, self.entity_description.bit, False)
