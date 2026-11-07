"""Start and end times of the inverter's charge and discharge time slots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LuxConfigEntry, LuxCoordinator
from .entity import LuxEntity
from .registers import TIME_SLOTS, decode_time, encode_time

PARALLEL_UPDATES = 1

SLOT_NAMES = {
    "ac_charge": "AC charge",
    "charge_priority": "Charge priority",
    "forced_discharge": "Forced discharge",
    "ac_first": "AC first",
}


@dataclass(frozen=True, kw_only=True)
class LuxTimeDescription(TimeEntityDescription):
    register: int


TIMES = [
    LuxTimeDescription(
        key=f"{slot}_{n}_{edge}",
        name=f"{SLOT_NAMES[slot]} slot {n} {edge}",
        register=start + offset,
        icon="mdi:clock-start" if edge == "start" else "mdi:clock-end",
    )
    for slot, starts in TIME_SLOTS.items()
    for n, start in enumerate(starts, 1)
    for edge, offset in (("start", 0), ("end", 1))
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(LuxTime(coordinator, description) for description in TIMES)


class LuxTime(LuxEntity, TimeEntity):
    """One end of a time slot."""

    _platform_domain = "time"
    _attr_entity_category = EntityCategory.CONFIG
    entity_description: LuxTimeDescription

    def __init__(self, coordinator: LuxCoordinator, description: LuxTimeDescription) -> None:
        super().__init__(coordinator, description)

    @property
    def available(self) -> bool:
        return (
            super().available and self.entity_description.register in self.coordinator.data.holdings
        )

    @property
    def native_value(self) -> time | None:
        value = self.coordinator.data.holdings.get(self.entity_description.register)
        return None if value is None else decode_time(value)

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_write(self.entity_description.register, encode_time(value))
