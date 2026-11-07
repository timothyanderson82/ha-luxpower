"""The TCP client against a fake dongle."""

import asyncio

import pytest

from custom_components.luxpower_local.client import (
    LuxClient,
    LuxConnectionError,
    LuxRejectedError,
    LuxTimeoutError,
)
from custom_components.luxpower_local.protocol import DeviceFunction

from .conftest import DATALOG, SERIAL, FakeDongle, heartbeat_frame


@pytest.fixture
async def client(dongle: FakeDongle):
    lux = LuxClient("127.0.0.1", dongle.port, DATALOG, reply_timeout=0.3)
    yield lux
    await lux.close()


async def test_reads_and_learns_serial(client: LuxClient, dongle: FakeDongle) -> None:
    assert client.inverter is None
    regs = await client.read_inputs(0, 40)
    assert regs[5] & 0xFF == 90
    assert client.inverter == SERIAL
    # Later requests carry the learnt serial
    await client.read_holdings(21, 1)
    assert dongle.received[-1][22:32] == SERIAL.encode()
    assert dongle.connections == 1


async def test_write(client: LuxClient, dongle: FakeDongle) -> None:
    assert await client.write_holding(105, 25) == 25
    assert dongle.holdings[105] == 25
    assert dongle.requests[-1] == (DeviceFunction.WRITE_SINGLE, 105, 25)


async def test_rejected(client: LuxClient, dongle: FakeDongle) -> None:
    dongle.reject.add(105)
    with pytest.raises(LuxRejectedError):
        await client.write_holding(105, 25)


async def test_heartbeat_is_echoed(client: LuxClient, dongle: FakeDongle) -> None:
    await client.read_inputs(0, 1)
    dongle.send_heartbeat()
    for _ in range(50):
        if heartbeat_frame() in dongle.received:
            break
        await asyncio.sleep(0.01)
    assert heartbeat_frame() in dongle.received


async def test_timeout_then_recovers(client: LuxClient, dongle: FakeDongle) -> None:
    dongle.mute = True
    with pytest.raises(LuxTimeoutError):
        await client.read_inputs(0, 40)
    assert not client.connected
    dongle.mute = False
    assert len(await client.read_inputs(0, 40)) == 40
    assert dongle.connections == 2


async def test_reconnects_after_drop(client: LuxClient, dongle: FakeDongle) -> None:
    await client.read_inputs(0, 1)
    dongle.disconnect_all()
    await asyncio.sleep(0.05)
    assert len(await client.read_inputs(40, 40)) == 40
    assert dongle.connections == 2


async def test_cannot_connect(dongle: FakeDongle) -> None:
    port = dongle.port
    await dongle.stop()
    lux = LuxClient("127.0.0.1", port, DATALOG)
    with pytest.raises(LuxConnectionError):
        await lux.read_inputs(0, 1)


async def test_requests_are_serialised(client: LuxClient, dongle: FakeDongle) -> None:
    results = await asyncio.gather(*(client.read_inputs(base, 40) for base in (0, 40, 80)))
    assert [len(r) for r in results] == [40, 40, 40]
    assert [r[1] for r in dongle.requests] == [0, 40, 80]
