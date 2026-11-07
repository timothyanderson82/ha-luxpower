"""Frames and register decoding, checked against recorded replies."""

from datetime import time

import pytest

from custom_components.luxpower_local.protocol import (
    DeviceFunction,
    FrameReader,
    ProtocolError,
    TcpFunction,
    build_request,
    crc16,
    parse_frame,
)
from custom_components.luxpower_local.registers import (
    FAULTS,
    WARNINGS,
    code_text,
    decode_inputs,
    decode_time,
    encode_time,
    status_text,
)

from .conftest import DATALOG, SERIAL, _recorded_registers, heartbeat_frame, recorded_frames


def test_crc16_modbus() -> None:
    # The standard check value for CRC-16/MODBUS
    assert crc16(b"123456789") == (0x4B37).to_bytes(2, "little")


def test_read_request_layout() -> None:
    frame = build_request(DATALOG, SERIAL, DeviceFunction.READ_INPUT, 40, 40)
    assert frame[:2] == b"\xa1\x1a"
    assert int.from_bytes(frame[2:4], "little") == 1
    assert int.from_bytes(frame[4:6], "little") == len(frame) - 6 == 32
    assert frame[7] == TcpFunction.TRANSLATED_DATA
    assert frame[8:18] == DATALOG.encode()
    data = frame[20:-2]
    assert int.from_bytes(frame[18:20], "little") == len(data) + 2
    assert data[0:2] == bytes([0, DeviceFunction.READ_INPUT])
    assert data[2:12] == SERIAL.encode()
    assert int.from_bytes(data[12:14], "little") == 40
    assert int.from_bytes(data[14:16], "little") == 40
    assert crc16(data) == frame[-2:]


def test_request_without_inverter_serial_is_blank() -> None:
    frame = build_request(DATALOG, None, DeviceFunction.READ_HOLD, 0, 40)
    assert frame[22:32] == b"\x00" * 10


def test_write_request_carries_value() -> None:
    frame = build_request(DATALOG, SERIAL, DeviceFunction.WRITE_SINGLE, 105, 20)
    data = frame[20:-2]
    assert data[1] == DeviceFunction.WRITE_SINGLE
    assert int.from_bytes(data[14:16], "little") == 20


def test_bad_serial_rejected() -> None:
    with pytest.raises(ValueError):
        build_request("SHORT", None, DeviceFunction.READ_HOLD, 0, 1)


def test_parse_recorded_replies() -> None:
    frames = [parse_frame(raw) for raw in recorded_frames()]
    assert [(f.device_function, f.register) for f in frames] == [
        (4, 0),
        (4, 40),
        (4, 80),
        (4, 120),
        (3, 0),
        (3, 40),
        (3, 80),
        (3, 120),
        (3, 160),
    ]
    for frame in frames:
        assert frame.datalog == DATALOG
        assert frame.inverter == SERIAL
        assert len(frame.registers) == 40
        assert not frame.is_error


def test_checksum_mismatch() -> None:
    raw = bytearray(recorded_frames()[0])
    raw[30] ^= 0xFF
    with pytest.raises(ProtocolError, match="checksum"):
        parse_frame(bytes(raw))


def test_reader_splits_and_joins_chunks() -> None:
    stream = b"".join(recorded_frames()[:3]) + heartbeat_frame()
    reader = FrameReader()
    frames = []
    # Feed in awkward pieces, including a split magic
    for i in range(0, len(stream), 7):
        frames += reader.feed(stream[i : i + 7])
    assert [f.register for f in frames[:3]] == [0, 40, 80]
    assert frames[3].tcp_function == TcpFunction.HEARTBEAT


def test_reader_resynchronises_after_garbage() -> None:
    good = recorded_frames()[1]
    corrupt = bytearray(recorded_frames()[0])
    corrupt[-1] ^= 0xFF
    frames = FrameReader().feed(b"junk" + bytes(corrupt) + good)
    assert [f.register for f in frames] == [40]


def test_decode_inputs() -> None:
    inputs, _ = _recorded_registers()
    values = decode_inputs(inputs)
    assert values["soc"] == 90
    assert values["soh"] == 98
    assert values["v_bat"] == 56.1
    assert values["v_ac_r"] == 218.6
    assert values["f_ac"] == 50.04
    assert values["p_pv"] == 35 + 33
    assert values["p_battery"] == 19
    assert values["p_grid"] == 3790
    assert values["e_pv_all"] == 18836.9
    assert values["e_chg_all"] == 1246.9
    assert values["e_dischg_all"] == 680.2
    assert values["t_bat"] == 46
    assert values["runtime"] == 90867626
    # BMS block
    assert values["max_chg_curr"] == 18.9
    assert values["max_dischg_curr"] == 100.0
    assert values["max_cell_voltage"] == 3.513
    assert values["min_cell_voltage"] == 3.5
    assert values["max_cell_temp"] == 26.0
    assert values["bat_capacity"] == 98
    assert status_text(values["status"]) == "PV & battery on-grid"


def test_decode_skips_unread_blocks() -> None:
    inputs, _ = _recorded_registers()
    values = decode_inputs({r: v for r, v in inputs.items() if r < 40})
    assert "soc" in values
    assert "e_pv_all" not in values
    assert "max_cell_voltage" not in values


def test_codes() -> None:
    assert code_text(0, FAULTS, "E") == "OK"
    assert code_text(1 << 16, WARNINGS, "W") == "W016: Grid power outage"
    assert code_text(1 << 6 | 1 << 19, FAULTS, "E") == "E006; E019: Bus voltage high"
    assert status_text(0x99) == "Unknown (0x99)"


def test_times() -> None:
    assert decode_time(23 | 59 << 8) == time(23, 59)
    assert decode_time(encode_time(time(6, 30))) == time(6, 30)
    assert decode_time(0xFFFF) is None
