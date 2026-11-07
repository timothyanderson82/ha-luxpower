"""Polls the inverter through its dongle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import LuxClient, LuxError
from .const import (
    CONF_HOLDING_INTERVAL,
    CONF_READ_BMS,
    CONF_SCAN_INTERVAL,
    DEFAULT_HOLDING_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAILURES_BEFORE_UNAVAILABLE,
)
from .registers import (
    BLOCK_SIZE,
    BMS_BLOCK,
    HOLDING_BLOCKS,
    INPUT_BLOCKS,
    LIFETIME_KEYS,
    decode_inputs,
)

_LOGGER = logging.getLogger(__name__)

type LuxConfigEntry = ConfigEntry[LuxCoordinator]


@dataclass
class LuxData:
    """The latest readings and settings."""

    inputs: dict[str, float | int] = field(default_factory=dict)
    holdings: dict[int, int] = field(default_factory=dict)


class LuxCoordinator(DataUpdateCoordinator[LuxData]):
    """Reads the input registers every poll and the settings less often."""

    config_entry: LuxConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LuxConfigEntry, client: LuxClient) -> None:
        options = entry.options
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.read_bms: bool = options.get(CONF_READ_BMS, True)
        self._holding_interval = timedelta(
            seconds=options.get(CONF_HOLDING_INTERVAL, DEFAULT_HOLDING_INTERVAL)
        )
        self._holdings_read: datetime | None = None
        self._failures = 0

    async def _async_update_data(self) -> LuxData:
        previous = self.data or LuxData()
        try:
            inputs = await self._read_inputs()
            holdings = previous.holdings
            now = dt_util.utcnow()
            if self._holdings_read is None or now - self._holdings_read >= self._holding_interval:
                holdings = await self._read_holdings()
                self._holdings_read = now
        except LuxError as err:
            self._failures += 1
            if self.data is not None and self._failures < FAILURES_BEFORE_UNAVAILABLE:
                _LOGGER.debug("Poll %s failed, keeping the last readings: %s", self._failures, err)
                return previous
            raise UpdateFailed(f"Cannot read the inverter: {err}") from err
        self._failures = 0

        values = decode_inputs(inputs)
        for key in LIFETIME_KEYS & values.keys():
            last = previous.inputs.get(key)
            if last is not None and values[key] < last:
                _LOGGER.debug("Ignoring %s going backwards from %s to %s", key, last, values[key])
                values[key] = last
        return LuxData(inputs=values, holdings=holdings)

    async def _read_inputs(self) -> dict[int, int]:
        blocks = (*INPUT_BLOCKS, BMS_BLOCK) if self.read_bms else INPUT_BLOCKS
        regs: dict[int, int] = {}
        for base in blocks:
            regs.update(enumerate(await self.client.read_inputs(base, BLOCK_SIZE), base))
        return regs

    async def _read_holdings(self) -> dict[int, int]:
        regs: dict[int, int] = {}
        for base in HOLDING_BLOCKS:
            regs.update(enumerate(await self.client.read_holdings(base, BLOCK_SIZE), base))
        return regs

    async def async_refresh_all(self) -> None:
        """Read everything now, settings included."""
        self._holdings_read = None
        await self.async_refresh()

    async def async_write(self, register: int, value: int) -> None:
        """Change one setting."""
        try:
            stored = await self.client.write_holding(register, value)
        except LuxError as err:
            raise HomeAssistantError(f"Could not change the inverter setting: {err}") from err
        self._update_holding(register, stored)

    async def async_set_bit(self, register: int, bit: int, on: bool) -> None:
        """Flip one bit of a setting, leaving the others as the inverter has them."""
        try:
            # Re-read first: the app or the inverter's screen may have changed it
            (current,) = await self.client.read_holdings(register, 1)
            value = current | bit if on else current & ~bit
            stored = await self.client.write_holding(register, value) if value != current else value
        except LuxError as err:
            raise HomeAssistantError(f"Could not change the inverter setting: {err}") from err
        self._update_holding(register, stored)

    def _update_holding(self, register: int, value: int) -> None:
        data = self.data or LuxData()
        self.async_set_updated_data(
            LuxData(inputs=data.inputs, holdings={**data.holdings, register: value})
        )
