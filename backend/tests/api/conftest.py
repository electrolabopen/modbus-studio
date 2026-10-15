"""API tests use the synchronous TestClient, which runs the app in its own
thread. The simulator therefore gets its own thread and event loop too."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from modbus_studio.config import Settings, get_settings
from modbus_studio.main import create_app
from modbus_studio.simulator import Simulator
from tests.integration.conftest import SimPorts, free_port

logging.getLogger("pymodbus").setLevel(logging.ERROR)


@pytest.fixture(scope="session")
def sim() -> Iterator[SimPorts]:
    ports = SimPorts(free_port(), free_port())
    loop = asyncio.new_event_loop()
    holder: list[Simulator] = []
    ready = threading.Event()

    async def start() -> None:
        # pymodbus servers must be created inside their event loop.
        holder.append(Simulator("127.0.0.1", ports.tcp, ports.rtu_tcp))
        await holder[0].start()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(start())
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(10), "simulator did not start"
    yield ports
    asyncio.run_coroutine_threadsafe(holder[0].stop(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(10)


@pytest.fixture
def make_client() -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def factory(**settings: Any) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, **settings)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


@pytest.fixture
def sim_conn(client: TestClient, sim: SimPorts) -> str:
    res = client.post(
        "/api/connections",
        json={"type": "tcp", "id": "sim", "host": "127.0.0.1", "port": sim.tcp, "timeout_s": 1},
    )
    assert res.status_code == 201, res.text
    return "sim"


def wait_for(fn: Callable[[], Any], timeout: float = 5.0) -> Any:
    """Call ``fn`` until it returns something truthy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.03)
    raise AssertionError("condition not met in time")
