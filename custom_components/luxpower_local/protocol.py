"""Frames spoken by a LuxPower Wi-Fi dongle on TCP port 8000.

Every frame starts ``A1 1A``, then a protocol number, the length of the rest of
the frame, a TCP function and the dongle ("datalog") serial. Data frames wrap a
Modbus-like request or reply for the inverter, with a CRC-16/MODBUS checksum.

Ported from lxp-bridge (https://github.com/celsworth/lxp-bridge, MIT).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

MAGIC = b"\xa1\x1a"
HEADER_LEN = 6  # magic, protocol and length; the length field counts what follows
SERIAL_LEN = 10
# The dongle fills in the inverter serial when a request leaves it blank
BLANK_SERIAL = b"\x00" * SERIAL_LEN


class TcpFunction(IntEnum):
    HEARTBEAT = 193
    TRANSLATED_DATA = 194
    READ_PARAM = 195
    WRITE_PARAM = 196


class DeviceFunction(IntEnum):
    READ_HOLD = 3
    READ_INPUT = 4
    WRITE_SINGLE = 6
    WRITE_MULTI = 16


# The inverter sets this bit on the device function when it rejects a request
ERROR_BIT = 0x80


class ProtocolError(Exception):
    """A frame could not be decoded."""


def crc16(data: bytes) -> bytes:
    """CRC-16/MODBUS, little-endian as it appears on the wire."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


def encode_serial(serial: str | None) -> bytes:
    """A serial as the 10 ASCII bytes the frames carry; blank when unknown."""
    if not serial:
        return BLANK_SERIAL
    raw = serial.encode("ascii")
    if len(raw) != SERIAL_LEN:
        raise ValueError(f"serial must be {SERIAL_LEN} characters")
    return raw


def decode_serial(raw: bytes) -> str:
    return raw.decode("ascii", errors="replace").strip("\x00")


@dataclass(frozen=True)
class Frame:
    """A frame received from the dongle."""

    tcp_function: int
    datalog: str
    raw: bytes
    # Only set for TRANSLATED_DATA frames
    device_function: int | None = None
    inverter: str | None = None
    register: int | None = None
    values: bytes = b""

    @property
    def is_error(self) -> bool:
        return self.device_function is not None and bool(self.device_function & ERROR_BIT)

    @property
    def registers(self) -> list[int]:
        """The values as 16-bit little-endian registers."""
        return [
            int.from_bytes(self.values[i : i + 2], "little") for i in range(0, len(self.values), 2)
        ]


def _wrap(protocol: int, tcp_function: TcpFunction, datalog: bytes, payload: bytes) -> bytes:
    length = 2 + SERIAL_LEN + len(payload)  # the 01 byte, TCP function, datalog, payload
    return (
        MAGIC
        + protocol.to_bytes(2, "little")
        + length.to_bytes(2, "little")
        + bytes([1, tcp_function])
        + datalog
        + payload
    )


def build_request(
    datalog: str,
    inverter: str | None,
    function: DeviceFunction,
    register: int,
    value: int,
) -> bytes:
    """A read (``value`` = register count) or single-register write."""
    if function not in (
        DeviceFunction.READ_HOLD,
        DeviceFunction.READ_INPUT,
        DeviceFunction.WRITE_SINGLE,
    ):
        raise ValueError(f"unsupported function {function!r}")
    # length (filled in below), address 0 = to the inverter, function, serial, register, value
    data = bytearray(2)
    data += bytes([0, function]) + encode_serial(inverter)
    data += register.to_bytes(2, "little") + value.to_bytes(2, "little")
    data[0:2] = len(data).to_bytes(2, "little")
    data += crc16(data[2:])
    return _wrap(1, TcpFunction.TRANSLATED_DATA, encode_serial(datalog), bytes(data))


def parse_frame(raw: bytes) -> Frame:
    """Decode one complete frame."""
    if len(raw) < HEADER_LEN + 2 + SERIAL_LEN or raw[:2] != MAGIC:
        raise ProtocolError("not a dongle frame")
    protocol = int.from_bytes(raw[2:4], "little")
    tcp_function = raw[7]
    datalog = decode_serial(raw[8:18])

    if tcp_function != TcpFunction.TRANSLATED_DATA:
        return Frame(tcp_function=tcp_function, datalog=datalog, raw=raw)

    data, checksum = raw[20:-2], raw[-2:]
    if len(data) < 14:
        raise ProtocolError("data frame too short")
    if crc16(data) != checksum:
        raise ProtocolError("checksum mismatch")

    function = data[1]
    values = data[14:]
    # Read replies on the newer protocols carry a byte count before the values
    if protocol != 1 and function & ~ERROR_BIT in (
        DeviceFunction.READ_HOLD,
        DeviceFunction.READ_INPUT,
    ):
        if not values or values[0] != len(values) - 1:
            raise ProtocolError("value length byte does not match")
        values = values[1:]

    return Frame(
        tcp_function=tcp_function,
        datalog=datalog,
        raw=raw,
        device_function=function,
        inverter=decode_serial(data[2:12]),
        register=int.from_bytes(data[12:14], "little"),
        values=bytes(values),
    )


class FrameReader:
    """Splits a TCP byte stream into frames."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[Frame]:
        self._buffer += chunk
        frames = []
        while True:
            start = self._buffer.find(MAGIC)
            if start < 0:
                # Keep a trailing A1 in case the magic is split across reads
                del self._buffer[: max(0, len(self._buffer) - 1)]
                return frames
            del self._buffer[:start]
            if len(self._buffer) < HEADER_LEN:
                return frames
            end = HEADER_LEN + int.from_bytes(self._buffer[4:6], "little")
            if len(self._buffer) < end:
                return frames
            raw = bytes(self._buffer[:end])
            try:
                frames.append(parse_frame(raw))
            except ProtocolError:
                # Skip past this magic and resynchronise on the next one
                del self._buffer[:2]
                continue
            del self._buffer[:end]
