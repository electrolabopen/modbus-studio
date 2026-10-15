"""Physical Modbus connections and the request serialisation around them.

Several polling windows may share one connection. Modbus RTU is half-duplex
and many TCP gateways only handle one outstanding request, so every
transaction on a connection goes through a single lock.

A request cancelled after it was sent (a window stopped mid-request) still gets
its reply. RTU frames carry no transaction id, so the next request first waits
for that reply to arrive and be dropped; otherwise it would be taken as its own.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pymodbus import FramerType
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException

from ..models.connection import (
    ConnectionConfig,
    RtuConnection,
    RtuOverTcpConnection,
    TcpConnection,
)
from ..models.poll import ReadFunction
from .serialports import open_error
from .traffic import Direction, TrafficLog

log = logging.getLogger(__name__)

# Inside a container 127.0.0.1 is the container itself, a classic docker-compose trap.
IN_CONTAINER = Path("/.dockerenv").exists()
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
# Opening a port to find out why it failed can hang (e.g. Bluetooth serial ports).
SERIAL_PROBE_TIMEOUT_S = 5.0
# Silence that ends a reply still arriving after its request was cancelled. RTU
# allows 1.5 character times inside a frame; TCP segments arrive back to back.
SETTLE_QUIET_S = 0.05

EXCEPTION_NAMES: dict[int, str] = {
    1: "Illegal function",
    2: "Illegal data address",
    3: "Illegal data value",
    4: "Server device failure",
    5: "Acknowledge",
    6: "Server device busy",
    8: "Memory parity error",
    10: "Gateway path unavailable",
    11: "Gateway target device failed to respond",
}


class ErrorKind(str, Enum):
    TIMEOUT = "timeout"
    EXCEPTION = "exception"  # the device answered with a Modbus exception response
    DISCONNECTED = "disconnected"
    INVALID = "invalid"  # malformed or mismatched response


class RequestError(Exception):
    def __init__(self, kind: ErrorKind, message: str, exception_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.exception_code = exception_code


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


@dataclass
class ConnectionStats:
    requests: int = 0
    responses: int = 0
    timeouts: int = 0
    exceptions: int = 0
    invalid: int = 0
    disconnected: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


ClientFactory = Callable[[ConnectionConfig, Callable[[bool, bytes], bytes]], Any]


def default_client_factory(cfg: ConnectionConfig, trace: Callable[[bool, bytes], bytes]) -> Any:
    common: dict[str, Any] = {
        "timeout": cfg.timeout_s,
        "retries": cfg.retries,
        "trace_packet": trace,
        # Reconnection is driven by the poller so that it is visible to the user.
        "reconnect_delay": 0,
    }
    if isinstance(cfg, TcpConnection):
        return AsyncModbusTcpClient(cfg.host, port=cfg.port, framer=FramerType.SOCKET, **common)
    if isinstance(cfg, RtuOverTcpConnection):
        return AsyncModbusTcpClient(cfg.host, port=cfg.port, framer=FramerType.RTU, **common)
    if isinstance(cfg, RtuConnection):
        return AsyncModbusSerialClient(
            cfg.serial_port,
            framer=FramerType.RTU,
            baudrate=cfg.baudrate,
            bytesize=cfg.bytesize,
            parity=cfg.parity,
            stopbits=cfg.stopbits,
            **common,
        )
    raise TypeError(f"unsupported connection type: {type(cfg).__name__}")


class Connection:
    def __init__(
        self,
        config: ConnectionConfig,
        traffic: TrafficLog,
        client_factory: ClientFactory = default_client_factory,
    ) -> None:
        self.config = config
        self.stats = ConnectionStats()
        self.state = ConnectionState.DISCONNECTED
        # Why the last connection attempt failed, for the UI; None once connected.
        self.last_error: str | None = None
        self._traffic = traffic
        self._client = client_factory(config, self._trace)
        self._lock = asyncio.Lock()
        # Monotonic times of the last frame sent and received, and an event set on
        # every received chunk; used to let the reply of a cancelled request pass.
        self._last_tx = self._last_rx = 0.0
        self._rx = asyncio.Event()
        self._settle_deadline: float | None = None

    @property
    def id(self) -> str:
        return self.config.id

    def _trace(self, sending: bool, data: bytes) -> bytes:
        self._traffic.record(self.id, Direction.TX if sending else Direction.RX, data)
        now = asyncio.get_running_loop().time()
        if sending:
            self._last_tx = now
        else:
            self._last_rx = now
            self._rx.set()
        return data

    async def _settle(self) -> None:
        """Let the reply of a cancelled request arrive (pymodbus drops it) first."""
        deadline, self._settle_deadline = self._settle_deadline, None
        if deadline is None:
            return
        loop = asyncio.get_running_loop()
        while (remaining := deadline - loop.time()) > 0:
            replying = self._last_rx > self._last_tx
            self._rx.clear()
            try:
                # Until the reply starts, then until it stops.
                await asyncio.wait_for(
                    self._rx.wait(), min(remaining, SETTLE_QUIET_S) if replying else remaining
                )
            except asyncio.TimeoutError:
                if replying:
                    return

    async def connect(self) -> bool:
        async with self._lock:
            return await self._ensure_connected()

    async def _ensure_connected(self) -> bool:
        if self._client.connected:
            self.state = ConnectionState.CONNECTED
            return True
        self.state = ConnectionState.CONNECTING
        # pymodbus only reports success or failure, so look up the name first: a mistyped
        # host is the most common mistake and deserves a precise message.
        error = await self._resolve_host()
        ok = False
        if error is None:
            try:
                ok = bool(await self._client.connect())
            except Exception as exc:  # serial ports raise OS-specific errors
                log.debug("connect %s failed: %s", self.id, exc)
                error = str(exc)
            if not ok:
                # A serial port explains itself better than pymodbus or pyserial do.
                error = await self._serial_open_error() or error or self._connect_failed_message()
        self.last_error = None if ok else error
        self.state = ConnectionState.CONNECTED if ok else ConnectionState.DISCONNECTED
        return ok

    async def _resolve_host(self) -> str | None:
        cfg = self.config
        if isinstance(cfg, RtuConnection):
            return None
        try:
            await asyncio.get_running_loop().getaddrinfo(
                cfg.host, cfg.port, type=socket.SOCK_STREAM
            )
        except OSError:
            return f"cannot resolve host {cfg.host!r}"
        return None

    async def _serial_open_error(self) -> str | None:
        """Why the serial port did not open (pymodbus only says that it did not)."""
        cfg = self.config
        if not isinstance(cfg, RtuConnection):
            return None
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    open_error,
                    cfg.serial_port,
                    baudrate=cfg.baudrate,
                    bytesize=cfg.bytesize,
                    parity=cfg.parity,
                    stopbits=cfg.stopbits,
                ),
                SERIAL_PROBE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            return f"serial port {cfg.serial_port} does not respond to open"

    def _connect_failed_message(self) -> str:
        cfg = self.config
        if isinstance(cfg, RtuConnection):
            return f"cannot open serial port {cfg.serial_port}"
        message = f"cannot connect to {cfg.host}:{cfg.port} (refused or timed out)"
        if IN_CONTAINER and cfg.host in LOOPBACK_HOSTS:
            message += (
                "; inside a container this address is the container itself,"
                " use the other service's name (e.g. 'simulator')"
            )
        return message

    async def close(self) -> None:
        async with self._lock:
            self._client.close()
            self.state = ConnectionState.DISCONNECTED

    async def _execute(self, call: Callable[[], Any]) -> Any:
        async with self._lock:
            if not await self._ensure_connected():
                self.stats.disconnected += 1
                raise RequestError(ErrorKind.DISCONNECTED, self.last_error or "not connected")
            await self._settle()
            self.stats.requests += 1
            started = asyncio.get_running_loop().time()
            try:
                result = await call()
            except asyncio.CancelledError:
                if self._last_tx >= started:
                    self._settle_deadline = self._last_tx + self.config.timeout_s
                raise
            except ConnectionException as exc:
                self.stats.disconnected += 1
                self.state = ConnectionState.DISCONNECTED
                self.last_error = str(exc)
                raise RequestError(ErrorKind.DISCONNECTED, str(exc)) from exc
            except ModbusIOException as exc:
                self.stats.timeouts += 1
                raise RequestError(ErrorKind.TIMEOUT, "no response (timeout)") from exc
            except ModbusException as exc:
                self.stats.invalid += 1
                raise RequestError(ErrorKind.INVALID, str(exc)) from exc
            finally:
                if self.config.delay_between_requests_ms:
                    await asyncio.sleep(self.config.delay_between_requests_ms / 1000)
            if result.isError():
                code = getattr(result, "exception_code", None)
                if code is None:
                    self.stats.invalid += 1
                    raise RequestError(ErrorKind.INVALID, str(result))
                self.stats.exceptions += 1
                name = EXCEPTION_NAMES.get(code, "Unknown exception")
                raise RequestError(ErrorKind.EXCEPTION, f"{name} ({code:02X}h)", code)
            self.stats.responses += 1
            return result

    async def read(
        self, function: ReadFunction, device_id: int, address: int, count: int
    ) -> list[int] | list[bool]:
        method = {
            ReadFunction.READ_COILS: self._client.read_coils,
            ReadFunction.READ_DISCRETE_INPUTS: self._client.read_discrete_inputs,
            ReadFunction.READ_HOLDING_REGISTERS: self._client.read_holding_registers,
            ReadFunction.READ_INPUT_REGISTERS: self._client.read_input_registers,
        }[function]
        result = await self._execute(lambda: method(address, count=count, device_id=device_id))
        if function.is_bit:
            # Bit responses are padded to a whole number of bytes.
            bits = list(result.bits)
            if len(bits) < count:
                self.stats.invalid += 1
                raise RequestError(ErrorKind.INVALID, f"expected {count} bits, got {len(bits)}")
            return [bool(b) for b in bits[:count]]
        registers = list(result.registers)
        if len(registers) != count:
            self.stats.invalid += 1
            raise RequestError(
                ErrorKind.INVALID, f"expected {count} registers, got {len(registers)}"
            )
        return registers

    async def write_coil(self, device_id: int, address: int, value: bool) -> None:
        """FC05 Write Single Coil."""
        await self._execute(lambda: self._client.write_coil(address, value, device_id=device_id))

    async def write_register(self, device_id: int, address: int, value: int) -> None:
        """FC06 Write Single Register."""
        await self._execute(
            lambda: self._client.write_register(address, value, device_id=device_id)
        )

    async def write_coils(self, device_id: int, address: int, values: Sequence[bool]) -> None:
        """FC15 Write Multiple Coils."""
        await self._execute(
            lambda: self._client.write_coils(address, list(values), device_id=device_id)
        )

    async def write_registers(self, device_id: int, address: int, values: Sequence[int]) -> None:
        """FC16 Write Multiple Registers."""
        await self._execute(
            lambda: self._client.write_registers(address, list(values), device_id=device_id)
        )


class ConnectionManager:
    def __init__(
        self, traffic: TrafficLog, client_factory: ClientFactory = default_client_factory
    ) -> None:
        self.traffic = traffic
        self._client_factory = client_factory
        self._connections: dict[str, Connection] = {}

    def add(self, config: ConnectionConfig) -> Connection:
        if config.id in self._connections:
            raise ValueError(f"connection {config.id!r} already exists")
        conn = Connection(config, self.traffic, self._client_factory)
        self._connections[config.id] = conn
        return conn

    def get(self, connection_id: str) -> Connection:
        try:
            return self._connections[connection_id]
        except KeyError:
            raise KeyError(f"unknown connection {connection_id!r}") from None

    def all(self) -> list[Connection]:
        return list(self._connections.values())

    async def remove(self, connection_id: str) -> None:
        conn = self._connections.pop(connection_id, None)
        if conn is not None:
            await conn.close()

    async def close_all(self) -> None:
        for conn in list(self._connections.values()):
            await conn.close()
        self._connections.clear()
