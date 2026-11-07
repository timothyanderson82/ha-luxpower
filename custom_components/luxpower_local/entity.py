"""Base entity for LuxPower Local."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_LEGACY_IDS, DOMAIN, MANUFACTURER
from .coordinator import LuxCoordinator


class LuxEntity(CoordinatorEntity[LuxCoordinator]):
    """An entity of one inverter."""

    _attr_has_entity_name = True
    # Set by each platform's classes, for the lxp-bridge entity IDs
    _platform_domain: str

    def __init__(
        self,
        coordinator: LuxCoordinator,
        description: EntityDescription,
        legacy_object_id: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        serial = entry.unique_id
        datalog = coordinator.client.datalog
        self._attr_unique_id = f"{serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(serial))},
            manufacturer=MANUFACTURER,
            name=entry.title,
            serial_number=serial,
        )
        # Take over lxp-bridge's entity IDs so history and the energy dashboard
        # carry on. Only used the first time the entity is registered.
        if legacy_object_id and entry.data.get(CONF_LEGACY_IDS):
            self.entity_id = f"{self._platform_domain}.lxp_{datalog.lower()}_{legacy_object_id}"
