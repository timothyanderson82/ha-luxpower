"""Entity IDs lxp-bridge's MQTT discovery gave the same readings and settings."""

from __future__ import annotations


def legacy_entity_ids(datalog: str) -> list[str]:
    """Every entity ID this integration takes over when asked to."""
    # Imported here: the platforms pull in all of Home Assistant's entity components
    from .number import NUMBERS
    from .sensor import SENSORS
    from .switch import SWITCHES

    pairs = [("sensor", d.legacy) for d in SENSORS]
    pairs += [("number", d.legacy) for d in NUMBERS]
    pairs += [("switch", d.legacy) for d in SWITCHES]
    return [f"{domain}.lxp_{datalog.lower()}_{legacy}" for domain, legacy in pairs if legacy]
