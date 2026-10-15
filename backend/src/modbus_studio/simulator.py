"""Modbus slave simulator for development, demos and integration tests.

Run with ``modbus-studio-sim``. It serves the same data on two ports:
Modbus TCP (default 5020) and RTU over TCP (default 5021).

Register map (identical for holding and input registers, 0-based addresses)::

    0       uint16   counter, +1 per second
    1       uint16   sawtooth 0..100, 10 s period
    2       int16    temperature x10, -50.0 .. 150.0 (scale 0.1)
    10-11   float32  sine, amplitude 100, 20 s period, ABCD
    12-13   float32  same value, CDAB
    14-15   float32  same value, BADC
    16-17   float32  same value, DCBA
    20-23   float64  same value, ABCD
    24-25   int32    -123456789, ABCD
    26-27   uint32   3000000000, CDAB
    100-199 free, writable (holding registers)

Coils 0-99 are writable. Discrete inputs 0-15 show a bit walking once per second.
Device IDs 1 and 2 are served; any other ID gets exception 04h (server device failure).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import math
import signal
import time
from collections.abc import Callable
from typing import Any

from pymodbus import FramerType
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType as SimType
from pymodbus.simulator import SimData, SimDevice

from .core.codec import ByteOrder, DataType, encode

log = logging.getLogger("modbus_studio.simulator")

REGISTER_COUNT = 200
COIL_COUNT = 100
DISCRETE_COUNT = 16
DEVICE_IDS = (1, 2)

CONST_INT32 = -123456789
CONST_UINT32 = 3_000_000_000


def sine(t: float) -> float:
    return 100.0 * math.sin(2 * math.pi * t / 20.0)


def dynamic_registers(t: float) -> dict[int, int]:
    """Values of the time-dependent registers at time ``t`` (seconds)."""
    s = sine(t)
    temperature = 50.0 + 100.0 * math.sin(2 * math.pi * t / 60.0)
    values = {
        0: int(t) & 0xFFFF,
        1: int((t % 10.0) * 10),
        2: encode(round(temperature * 10), DataType.INT16)[0],
    }
    blocks: list[tuple[int, DataType, ByteOrder, int | float]] = [
        (10, DataType.FLOAT32, ByteOrder.ABCD, s),
        (12, DataType.FLOAT32, ByteOrder.CDAB, s),
        (14, DataType.FLOAT32, ByteOrder.BADC, s),
        (16, DataType.FLOAT32, ByteOrder.DCBA, s),
        (20, DataType.FLOAT64, ByteOrder.ABCD, s),
        (24, DataType.INT32, ByteOrder.ABCD, CONST_INT32),
        (26, DataType.UINT32, ByteOrder.CDAB, CONST_UINT32),
    ]
    for start, dtype, order, value in blocks:
        for i, word in enumerate(encode(value, dtype, order)):
            values[start + i] = word
    return values


def make_action(clock: Callable[[], float]) -> Any:
    async def action(
        function_code: int,
        start_address: int,
        address: int,
        count: int,
        registers: list[int],
        set_values: list[int] | list[bool] | None,
    ) -> None:
        if set_values is not None:
            return None
        t = clock()
        if function_code in (3, 4):
            for addr, value in dynamic_registers(t).items():
                idx = addr - start_address
                if 0 <= idx < len(registers):
                    registers[idx] = value
        elif function_code == 2 and registers:
            # Bits are packed 16 per word, least significant bit first.
            registers[0] = 1 << (int(t) % DISCRETE_COUNT)
        return None

    return action


def build_devices(clock: Callable[[], float] = time.time) -> list[SimDevice]:
    action = make_action(clock)
    return [
        SimDevice(
            device_id,
            simdata=(
                [SimData(0, count=COIL_COUNT, values=False, datatype=SimType.BITS)],
                [SimData(0, count=DISCRETE_COUNT, values=False, datatype=SimType.BITS)],
                [SimData(0, count=REGISTER_COUNT, values=0, datatype=SimType.REGISTERS)],
                [SimData(0, count=REGISTER_COUNT, values=0, datatype=SimType.REGISTERS)],
            ),
            action=action,
        )
        for device_id in DEVICE_IDS
    ]


class Simulator:
    def __init__(self, host: str = "0.0.0.0", tcp_port: int = 5020, rtu_tcp_port: int = 5021):
        self.servers = [
            ModbusTcpServer(build_devices(), framer=FramerType.SOCKET, address=(host, tcp_port)),
            ModbusTcpServer(build_devices(), framer=FramerType.RTU, address=(host, rtu_tcp_port)),
        ]
        self._tasks: list[asyncio.Task[Any]] = []

    async def start(self) -> None:
        for server in self.servers:
            self._tasks.append(asyncio.create_task(server.serve_forever()))
        # serve_forever() binds asynchronously; wait until both are listening.
        for _ in range(100):
            if all(s.is_active() for s in self.servers):
                return
            await asyncio.sleep(0.02)
        raise RuntimeError("simulator failed to start")

    async def stop(self) -> None:
        for server in self.servers:
            await server.shutdown()  # type: ignore[no-untyped-call]
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


async def _serve(host: str, tcp_port: int, rtu_tcp_port: int) -> None:
    sim = Simulator(host, tcp_port, rtu_tcp_port)
    await sim.start()
    log.info("Modbus TCP on %s:%d, RTU over TCP on %s:%d", host, tcp_port, host, rtu_tcp_port)
    stop = asyncio.Event()
    # As PID 1 in a container SIGTERM has no default action: without a handler
    # `docker compose stop` waits 10 s and then kills the process.
    with contextlib.suppress(NotImplementedError):  # no signal handlers on Windows
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    try:
        await stop.wait()
    finally:
        await sim.stop()


def run() -> None:
    parser = argparse.ArgumentParser(description="modbus-studio slave simulator")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--tcp-port", type=int, default=5020)
    parser.add_argument("--rtu-tcp-port", type=int, default=5021)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("pymodbus").setLevel(logging.ERROR)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(args.host, args.tcp_port, args.rtu_tcp_port))


if __name__ == "__main__":
    run()
