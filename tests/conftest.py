"""Fixtures for LuxPower Local tests: a fake dongle on localhost.

The register values come from replies recorded from an SNA5000, with the real
serials swapped for DATALOG and SERIAL.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.luxpower_local.const import CONF_DATALOG, CONF_LEGACY_IDS, DOMAIN
from custom_components.luxpower_local.protocol import (
    MAGIC,
    DeviceFunction,
    FrameReader,
    TcpFunction,
    crc16,
)

DATALOG = "AB12345678"
SERIAL = "0123456789"
FIXTURES = Path(__file__).parent / "fixtures"


def recorded_frames() -> list[bytes]:
    return [bytes.fromhex(line) for line in (FIXTURES / "replies.txt").read_text().split()]


def _recorded_registers() -> tuple[dict[int, int], dict[int, int]]:
    inputs: dict[int, int] = {}
    holdings: dict[int, int] = {}
    reader = FrameReader()
    for frame in reader.feed(b"".join(recorded_frames())):
        target = inputs if frame.device_function == DeviceFunction.READ_INPUT else holdings
        target.update(enumerate(frame.registers, frame.register))
    return inputs, holdings


def reply_frame(function: int, register: int, values: bytes, *, length_byte: bool) -> bytes:
    """A frame as the dongle sends it (protocol 5, address 1)."""
    data = bytes([1, function]) + SERIAL.encode() + register.to_bytes(2, "little")
    if length_byte:
        data += bytes([len(values)])
    data += values
    body = bytes([1, TcpFunction.TRANSLATED_DATA]) + DATALOG.encode()
    body += (len(data) + 2).to_bytes(2, "little") + data + crc16(data)
    return MAGIC + (5).to_bytes(2, "little") + len(body).to_bytes(2, "little") + body


def heartbeat_frame() -> bytes:
    body = bytes([1, TcpFunction.HEARTBEAT]) + DATALOG.encode() + b"\x00"
    return MAGIC + (2).to_bytes(2, "little") + len(body).to_bytes(2, "little") + body


class FakeDongle:
    """Answers reads and writes from register maps, like the real dongle."""

    def __init__(self) -> None:
        self.inputs, self.holdings = _recorded_registers()
        self.requests: list[tuple[int, int, int]] = []  # function, register, value
        self.received: list[bytes] = []  # every frame the client sent
        self.mute = False  # stop answering, as when the dongle's Wi-Fi drops
        self.drop = False  # close the connection on every request
        self.reject: set[int] = set()  # registers to answer with an error
        self.connections = 0
        self.port = 0
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self.disconnect_all()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def disconnect_all(self) -> None:
        for writer in self._writers:
            writer.close()
        self._writers.clear()

    def send_heartbeat(self) -> None:
        for writer in self._writers:
            writer.write(heartbeat_frame())

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._writers.append(writer)
        buffer = b""
        try:
            while chunk := await reader.read(4096):
                buffer += chunk
                while len(buffer) >= 6 and len(buffer) >= 6 + int.from_bytes(buffer[4:6], "little"):
                    end = 6 + int.from_bytes(buffer[4:6], "little")
                    frame, buffer = buffer[:end], buffer[end:]
                    self.received.append(frame)
                    if self.drop:
                        writer.close()
                        return
                    if frame[7] == TcpFunction.TRANSLATED_DATA and not self.mute:
                        writer.write(self._answer(frame))
        except ConnectionError:
            pass
        finally:
            writer.close()

    def _answer(self, frame: bytes) -> bytes:
        data = frame[20:-2]
        assert crc16(data) == frame[-2:], "client sent a bad checksum"
        assert frame[8:18] == DATALOG.encode(), "client sent the wrong datalog"
        function = data[1]
        register = int.from_bytes(data[12:14], "little")
        value = int.from_bytes(data[14:16], "little")
        self.requests.append((function, register, value))
        if register in self.reject:
            return reply_frame(function | 0x80, register, b"\x00\x00", length_byte=False)
        if function == DeviceFunction.WRITE_SINGLE:
            self.holdings[register] = value
            return reply_frame(function, register, value.to_bytes(2, "little"), length_byte=False)
        source = self.inputs if function == DeviceFunction.READ_INPUT else self.holdings
        values = b"".join(
            source.get(r, 0).to_bytes(2, "little") for r in range(register, register + value)
        )
        return reply_frame(function, register, values, length_byte=True)


@pytest.fixture(autouse=True)
def short_reply_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Muted-dongle tests would otherwise wait the full five seconds."""
    monkeypatch.setattr("custom_components.luxpower_local.client.REPLY_TIMEOUT", 0.3)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading custom_components/."""


@pytest.fixture
async def dongle(socket_enabled: None) -> AsyncGenerator[FakeDongle]:
    """A fake dongle; sockets are allowed, to localhost only."""
    fake = FakeDongle()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def entry(dongle: FakeDongle) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Inverter",
        unique_id=SERIAL,
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: dongle.port,
            CONF_DATALOG: DATALOG,
            CONF_LEGACY_IDS: False,
        },
    )
