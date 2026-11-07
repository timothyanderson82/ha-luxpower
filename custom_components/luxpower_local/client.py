"""An asyncio connection to a LuxPower Wi-Fi dongle."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .protocol import DeviceFunction, Frame, FrameReader, TcpFunction, build_request

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
REPLY_TIMEOUT = 5


class LuxError(Exception):
    """The dongle could not be reached or did not answer."""


class LuxConnectionError(LuxError):
    """The TCP connection failed or dropped."""


class LuxTimeoutError(LuxError):
    """The dongle did not answer in time."""


class LuxRejectedError(LuxError):
    """The inverter rejected a request."""


class LuxClient:
    """Talks to one inverter through its dongle.

    One request is in flight at a time. The dongle only sends replies to the
    connection that asked, so other clients (the LuxPower cloud, lxp-bridge)
    do not interfere.
    """

    def __init__(
        self,
        host: str,
        port: int,
        datalog: str,
        inverter: str | None = None,
        reply_timeout: float | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.datalog = datalog
        # Learnt from the first reply when not given
        self.inverter = inverter
        self._reply_timeout = reply_timeout or REPLY_TIMEOUT
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listener: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._pending: tuple[int, int, asyncio.Future[Frame]] | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
            )
        except (OSError, TimeoutError) as err:
            raise LuxConnectionError(f"cannot connect to {self.host}:{self.port}: {err}") from err
        self._listener = asyncio.get_running_loop().create_task(self._listen())
        _LOGGER.debug("Connected to %s:%s", self.host, self.port)

    async def close(self) -> None:
        listener, self._listener = self._listener, None
        if listener and listener is not asyncio.current_task():
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
        self._drop(LuxConnectionError("connection closed"))

    def _drop(self, err: LuxError) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer:
            writer.close()
        if self._pending and not self._pending[2].done():
            self._pending[2].set_exception(err)

    async def _listen(self) -> None:
        assert self._reader
        frames = FrameReader()
        try:
            while chunk := await self._reader.read(4096):
                for frame in frames.feed(chunk):
                    self._handle(frame)
            err = LuxConnectionError("dongle closed the connection")
        except OSError as err_:
            err = LuxConnectionError(str(err_))
        _LOGGER.debug("Disconnected from %s:%s: %s", self.host, self.port, err)
        self._drop(err)

    def _handle(self, frame: Frame) -> None:
        if frame.tcp_function == TcpFunction.HEARTBEAT:
            # The dongle drops clients that do not echo its heartbeats
            if self._writer:
                self._writer.write(frame.raw)
            return
        if frame.tcp_function != TcpFunction.TRANSLATED_DATA or self._pending is None:
            return
        function, register, future = self._pending
        matches = frame.register == register and frame.device_function in (
            function,
            function | 0x80,
        )
        if matches and not future.done():
            future.set_result(frame)

    async def _request(self, function: DeviceFunction, register: int, value: int) -> Frame:
        async with self._lock:
            await self.connect()
            assert self._writer
            future: asyncio.Future[Frame] = asyncio.get_running_loop().create_future()
            self._pending = (function, register, future)
            try:
                self._writer.write(
                    build_request(self.datalog, self.inverter, function, register, value)
                )
                await self._writer.drain()
                frame = await asyncio.wait_for(future, self._reply_timeout)
            except TimeoutError as err:
                # A late reply would be mistaken for the next request's; start afresh
                await self.close()
                raise LuxTimeoutError(
                    f"no reply to {function.name} {register} from {self.host}"
                ) from err
            except OSError as err:
                await self.close()
                raise LuxConnectionError(str(err)) from err
            finally:
                self._pending = None

        if frame.is_error:
            raise LuxRejectedError(f"inverter rejected {function.name} {register}")
        if frame.inverter and not self.inverter:
            self.inverter = frame.inverter
        return frame

    async def read_inputs(self, register: int, count: int) -> list[int]:
        frame = await self._request(DeviceFunction.READ_INPUT, register, count)
        return frame.registers

    async def read_holdings(self, register: int, count: int) -> list[int]:
        frame = await self._request(DeviceFunction.READ_HOLD, register, count)
        return frame.registers

    async def write_holding(self, register: int, value: int) -> int:
        """Set one holding register; returns the value the inverter reports back."""
        frame = await self._request(DeviceFunction.WRITE_SINGLE, register, value)
        return frame.registers[0] if frame.values else value
