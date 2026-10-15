"""Polled values reach InfluxDB, and InfluxDB never slows down polling."""

import asyncio

import httpx

from modbus_studio.core.studio import Studio
from modbus_studio.models import PollDefinition, TcpConnection
from modbus_studio.models.exporters import InfluxDBConfig
from modbus_studio.models.format import RegisterFormatModel

CONFIG = InfluxDBConfig(
    enabled=True, url="http://influx:8086", org="plant", bucket="modbus", token="t",
    flush_interval_ms=100,
)  # fmt: skip


def window(**overrides) -> PollDefinition:
    values = {
        "id": "w",
        "name": "Simulator",
        "connection_id": "sim",
        "address": 0,
        "quantity": 4,
        "scan_rate_ms": 50,
        "formats": {
            0: RegisterFormatModel(dtype="uint16", alias="counter"),
            2: RegisterFormatModel(scale=0.1, unit="°C", alias="temperature"),
        },
    }
    return PollDefinition(**{**values, **overrides})


async def test_polled_values_are_written_with_their_tags(simulator):
    lines: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        lines.extend(request.content.decode().splitlines())
        return httpx.Response(204)

    studio = Studio(influx_transport=httpx.MockTransport(handle))
    try:
        studio.add_connection(
            TcpConnection(id="sim", name="Sim", host="127.0.0.1", port=simulator.tcp)
        )
        studio.set_influxdb(CONFIG)
        studio.add_poll(window())
        for _ in range(100):
            if studio.influx.status.points_sent >= 8:
                break
            await asyncio.sleep(0.05)
    finally:
        await studio.close()

    assert studio.influx.status.points_sent >= 8
    first = {line.split(" ")[0]: line.split(" ")[1] for line in lines[:4]}
    assert set(first) == {
        "Simulator,address=0,alias=counter,connection=Sim,device=1",
        "Simulator,address=1,alias=1,connection=Sim,device=1",
        "Simulator,address=2,alias=temperature,connection=Sim,device=1,unit=°C",
        "Simulator,address=3,alias=3,connection=Sim,device=1",
    }
    temperature = float(first[next(k for k in first if "temperature" in k)].split("=")[1])
    assert -50.0 <= temperature <= 150.0  # scaled, not the raw x10 register


async def test_a_hung_influxdb_does_not_slow_polling(simulator):
    async def hang(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3600)
        return httpx.Response(204)

    studio = Studio(influx_transport=httpx.MockTransport(hang))
    try:
        studio.add_connection(TcpConnection(id="sim", host="127.0.0.1", port=simulator.tcp))
        studio.set_influxdb(CONFIG.model_copy(update={"batch_size": 1}))
        task = studio.add_poll(window(scan_rate_ms=20))
        await asyncio.sleep(1.0)
        polls = studio.polls.get(task.definition.id).stats.valid
    finally:
        studio.influx.config = studio.influx.config.model_copy(update={"timeout_s": 0.1})
        await studio.close()
    # 1 s at 20 ms is 50 polls; allow for a slow CI runner, but not for waiting on InfluxDB.
    assert polls >= 25
    assert studio.influx.status.pending > 0 and studio.influx.status.points_sent == 0
