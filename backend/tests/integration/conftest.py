import asyncio
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from modbus_studio.core.connection import Connection, ConnectionManager
from modbus_studio.core.traffic import TrafficLog
from modbus_studio.models import RtuOverTcpConnection, TcpConnection
from modbus_studio.simulator import SerialLine, Simulator

logging.getLogger("pymodbus").setLevel(logging.ERROR)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class SimPorts:
    tcp: int
    rtu_tcp: int


@pytest.fixture
async def simulator() -> AsyncIterator[SimPorts]:
    ports = SimPorts(free_port(), free_port())
    sim = Simulator("127.0.0.1", ports.tcp, ports.rtu_tcp)
    await sim.start()
    yield ports
    await sim.stop()


@pytest.fixture
def traffic() -> TrafficLog:
    return TrafficLog()


@pytest.fixture
async def manager(traffic: TrafficLog) -> AsyncIterator[ConnectionManager]:
    mgr = ConnectionManager(traffic)
    yield mgr
    await mgr.close_all()


@pytest.fixture
async def tcp(manager: ConnectionManager, simulator: SimPorts) -> Connection:
    return manager.add(TcpConnection(id="tcp", host="127.0.0.1", port=simulator.tcp))


@pytest.fixture
async def rtu_tcp(manager: ConnectionManager, simulator: SimPorts) -> Connection:
    return manager.add(RtuOverTcpConnection(id="rtu", host="127.0.0.1", port=simulator.rtu_tcp))


@pytest.fixture(params=["tcp", "rtu_tcp"])
async def any_conn(request, manager: ConnectionManager, simulator: SimPorts) -> Connection:
    """The simulator reached over each TCP-based transport."""
    if request.param == "tcp":
        return manager.add(TcpConnection(id="tcp", host="127.0.0.1", port=simulator.tcp))
    return manager.add(RtuOverTcpConnection(id="rtu", host="127.0.0.1", port=simulator.rtu_tcp))


@pytest.fixture
async def silent_port() -> AsyncIterator[int]:
    """A TCP server that accepts connections and never answers."""
    writers: list[asyncio.StreamWriter] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    for w in writers:
        w.close()
    server.close()
    await server.wait_closed()


# Two serial ports wired to each other, e.g. a com0com pair on Windows: "COM10,COM11".
SERIAL_PAIR_ENV = "MODBUS_STUDIO_TEST_SERIAL_PAIR"


@pytest.fixture
def serial_pair(tmp_path: Path) -> Iterator[tuple[str, str]]:
    """Two connected serial ports: a socat pty pair on Linux, or the pair in the env var."""
    if pair := os.environ.get(SERIAL_PAIR_ENV):
        a, b = (p.strip() for p in pair.split(","))
        yield a, b
        return
    socat = shutil.which("socat")
    if not sys.platform.startswith("linux") or socat is None:
        if sys.platform.startswith("linux") and os.environ.get("CI"):
            pytest.fail("socat is not installed: the RTU serial tests would be skipped")
        pytest.skip(f"needs socat on Linux, or {SERIAL_PAIR_ENV}=PORT_A,PORT_B")
    a, b = tmp_path / "sim", tmp_path / "studio"
    proc = subprocess.Popen(
        [socat, f"pty,raw,echo=0,link={a}", f"pty,raw,echo=0,link={b}"],
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if a.exists() and b.exists():
                break
            if proc.poll() is not None:
                pytest.fail("socat exited")
            time.sleep(0.02)
        else:
            pytest.fail("socat did not create the pty pair")
        yield str(a), str(b)
    finally:
        proc.terminate()
        proc.wait(5)


@pytest.fixture
async def serial_simulator(serial_pair: tuple[str, str]) -> AsyncIterator[str]:
    """The simulator as an RTU slave on one end of the pair; yields the other end.

    The line is 8N1: Linux pseudo-terminals refuse parity.
    """
    sim = Simulator(tcp_port=0, rtu_tcp_port=0, serial=SerialLine(serial_pair[0], parity="N"))
    await sim.start()
    yield serial_pair[1]
    await sim.stop()
