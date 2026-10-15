import asyncio
import logging
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from modbus_studio.core.connection import Connection, ConnectionManager
from modbus_studio.core.traffic import TrafficLog
from modbus_studio.models import RtuOverTcpConnection, TcpConnection
from modbus_studio.simulator import Simulator

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
