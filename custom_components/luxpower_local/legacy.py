"""Entity IDs lxp-bridge's MQTT discovery gave the same readings and settings."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def legacy_ids(datalog: str) -> list[tuple[str, str, str]]:
    """(platform, description key, lxp-bridge entity ID) for every entity taken over."""
    # Imported here: the platforms pull in all of Home Assistant's entity components
    from .number import NUMBERS
    from .sensor import SENSORS
    from .switch import SWITCHES

    found = [("sensor", d.key, d.legacy) for d in SENSORS]
    found += [("number", d.key, d.legacy) for d in NUMBERS]
    found += [("switch", d.key, d.legacy) for d in SWITCHES]
    return [
        (platform, key, f"{platform}.lxp_{datalog.lower()}_{legacy}")
        for platform, key, legacy in found
        if legacy
    ]


def legacy_entity_ids(datalog: str) -> list[str]:
    """Every entity ID this integration takes over when asked to."""
    return [entity_id for _, _, entity_id in legacy_ids(datalog)]


@callback
def async_adopt_legacy_ids(hass: HomeAssistant, serial: str, datalog: str) -> None:
    """Move already-registered entities onto their lxp-bridge IDs.

    New entities get those IDs when first added, but Home Assistant gives an
    entity back its previous ID when its config entry is deleted and added
    again. The recorder keeps the history already stored under the lxp-bridge
    ID, so the entity carries on from it.
    """
    registry = er.async_get(hass)
    for platform, key, target in legacy_ids(datalog):
        current = registry.async_get_entity_id(platform, DOMAIN, f"{serial}_{key}")
        if current is None or current == target:
            continue
        if registry.async_get(target):
            _LOGGER.warning("Cannot rename %s to %s: that ID is in use", current, target)
            continue
        registry.async_update_entity(current, new_entity_id=target)
        _LOGGER.info("Renamed %s to %s", current, target)

    # 0.1.0 showed total runtime in hours; lxp-bridge's statistics are in seconds
    runtime = registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_runtime")
    entry = registry.async_get(runtime) if runtime else None
    if entry and entry.options.get("sensor.private", {}).get("suggested_unit_of_measurement"):
        registry.async_update_entity_options(entry.entity_id, "sensor.private", None)
