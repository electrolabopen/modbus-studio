import asyncio
import time

import httpx
import pytest

from modbus_studio.core.influx import InfluxExporter, Sample, to_line
from modbus_studio.models.exporters import InfluxDBConfig

T = 1_700_000_000.123456789


def sample(**overrides) -> Sample:
    values = {
        "window": "Boiler",
        "connection": "plc",
        "device": 1,
        "address": 2,
        "alias": "temperature",
        "unit": "°C",
        "value": 21.5,
        "timestamp": T,
    }
    return Sample(**{**values, **overrides})


def test_line_protocol():
    assert to_line(sample()) == (
        "Boiler,address=2,alias=temperature,connection=plc,device=1,unit=°C"
        f" value=21.5 {round(T * 1e9)}"
    )


def test_integers_are_written_as_floats_and_bits_as_booleans():
    # A field must keep its type: an int16 that later gets scale 0.1 becomes a float.
    assert " value=42.0 " in to_line(sample(value=42))
    assert " value=true " in to_line(sample(value=True))
    assert " value=false " in to_line(sample(value=False))


def test_scaling_noise_is_rounded_away():
    assert " value=115.3 " in to_line(sample(value=1153 * 0.1))
    assert " value=84.4302444458008 " in to_line(sample(value=84.43024444580078))
    assert " value=1.5e-20 " in to_line(sample(value=1.5e-20))


def test_names_are_escaped_and_empty_tags_left_out():
    line = to_line(sample(window="Pump 1, line=A", alias="flow, m3/h", unit="", connection="a=b"))
    assert line.startswith(r"Pump\ 1\,\ line=A,address=2,alias=flow\,\ m3/h,connection=a\=b,")
    assert "unit=" not in line
    assert "\n" not in to_line(sample(alias="two\nlines"))


def test_without_alias_the_address_is_the_alias():
    assert ",alias=7," in to_line(sample(alias="", address=7))


def test_values_influxdb_cannot_store_are_skipped():
    assert to_line(sample(value=float("nan"))) is None
    assert to_line(sample(value=float("inf"))) is None


CONFIG = InfluxDBConfig(
    enabled=True,
    url="http://influx:8086/",
    org="plant",
    bucket="modbus",
    token="secret",
    flush_interval_ms=100,
)


class FakeInflux:
    """An InfluxDB write endpoint with a programmable answer."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 204
        self.body = b""
        self.delay = 0.0

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        return httpx.Response(self.status, content=self.body)

    @property
    def lines(self) -> list[str]:
        return [line for r in self.requests for line in r.content.decode().splitlines()]


@pytest.fixture
async def influx():
    fake = FakeInflux()
    exporter = InfluxExporter(httpx.MockTransport(fake.handle))
    yield fake, exporter
    await exporter.close()


async def wait_for(check, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


async def test_points_are_written_in_batches(influx):
    fake, exporter = influx
    exporter.configure(CONFIG)
    exporter.offer([sample(address=a, alias="") for a in range(3)])
    await wait_for(lambda: exporter.status.points_sent == 3)
    request = fake.requests[0]
    assert request.url.path == "/api/v2/write"
    assert dict(request.url.params) == {"org": "plant", "bucket": "modbus", "precision": "ns"}
    assert request.headers["authorization"] == "Token secret"
    assert len(fake.lines) == 3
    status = exporter.status
    assert (status.state, status.writes, status.pending, status.errors) == ("ok", 1, 0, 0)


async def test_nothing_is_queued_while_disabled_or_incomplete(influx):
    _, exporter = influx
    exporter.offer([sample()])
    assert exporter.status.state == "disabled" and exporter.status.pending == 0
    exporter.configure(CONFIG.model_copy(update={"token": None}))
    assert exporter.status.state == "incomplete"
    exporter.offer([sample()])
    assert exporter.status.pending == 0


async def test_aliased_only(influx):
    fake, exporter = influx
    exporter.configure(CONFIG.model_copy(update={"aliased_only": True}))
    exporter.offer([sample(alias=""), sample(alias="flow")])
    await wait_for(lambda: exporter.status.points_sent == 1)
    assert ",alias=flow," in fake.lines[0]


async def test_points_wait_while_influxdb_is_down_and_go_out_when_it_is_back(influx, monkeypatch):
    monkeypatch.setattr("modbus_studio.core.influx.RETRY_MIN_S", 0.05)
    fake, exporter = influx
    fake.status, fake.body = 503, b'{"code":"unavailable","message":"starting up"}'
    exporter.configure(CONFIG)
    exporter.offer([sample(), sample(address=3)])
    await wait_for(lambda: exporter.status.errors >= 1)
    assert exporter.status.state == "error"
    assert exporter.status.last_error == "HTTP 503 (starting up)"
    assert exporter.status.pending == 2
    fake.status = 204
    await wait_for(lambda: exporter.status.points_sent == 2)
    assert exporter.status.state == "ok" and exporter.status.pending == 0


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (
            401,
            b'{"code":"unauthorized","message":"unauthorized access"}',
            "unauthorized: check the token (unauthorized access)",
        ),
        (
            404,
            b'{"code":"not found","message":"bucket \\"x\\" not found"}',
            'not found: check the org and the bucket (bucket "x" not found)',
        ),
    ],
)
async def test_errors_say_what_to_check(influx, status, body, message):
    fake, exporter = influx
    fake.status, fake.body = status, body
    exporter.configure(CONFIG)
    exporter.offer([sample()])
    await wait_for(lambda: exporter.status.errors >= 1)
    assert exporter.status.last_error == message
    assert exporter.status.pending == 1  # kept: fixing the settings sends them


async def test_unreachable_server(monkeypatch):
    async def refuse(request):
        raise httpx.ConnectError("connection refused")

    exporter = InfluxExporter(httpx.MockTransport(refuse))
    exporter.configure(CONFIG)
    exporter.offer([sample()])
    await wait_for(lambda: exporter.status.errors >= 1)
    assert exporter.status.last_error == "cannot connect to http://influx:8086: connection refused"
    await exporter.close()


async def test_rejected_points_are_dropped_so_the_rest_keep_flowing(influx):
    fake, exporter = influx
    fake.status, fake.body = 400, b'{"code":"invalid","message":"field type conflict"}'
    exporter.configure(CONFIG)
    exporter.offer([sample()])
    await wait_for(lambda: exporter.status.dropped == 1)
    assert exporter.status.pending == 0
    assert exporter.status.last_error == "HTTP 400 (field type conflict); 1 points dropped"


async def test_a_full_buffer_drops_the_oldest_points(influx):
    fake, exporter = influx
    fake.status = 503
    exporter.configure(CONFIG.model_copy(update={"buffer_size": 100, "flush_interval_ms": 60_000}))
    exporter.offer([sample(address=a) for a in range(150)])
    assert exporter.status.pending == 100 and exporter.status.dropped == 50


async def test_offer_never_waits_for_a_slow_server(influx):
    fake, exporter = influx
    fake.delay = 10
    exporter.configure(CONFIG.model_copy(update={"batch_size": 10}))
    exporter.offer([sample(address=a) for a in range(10)])
    await wait_for(lambda: fake.requests)  # a write is now hanging
    started = time.monotonic()
    for _ in range(100):
        exporter.offer([sample(address=a) for a in range(10)])
    assert time.monotonic() - started < 0.5
    assert exporter.status.pending == 1010
    fake.delay = 0  # let close() flush quickly


async def test_close_writes_what_is_left(influx):
    fake, exporter = influx
    exporter.configure(CONFIG.model_copy(update={"flush_interval_ms": 60_000}))
    exporter.offer([sample()])
    await exporter.close()
    assert len(fake.lines) == 1


async def test_changing_the_destination_discards_unsent_points(influx):
    fake, exporter = influx
    fake.status = 503
    exporter.configure(CONFIG.model_copy(update={"flush_interval_ms": 60_000}))
    exporter.offer([sample()])
    exporter.configure(CONFIG.model_copy(update={"flush_interval_ms": 60_000, "token": "new"}))
    assert exporter.status.pending == 1  # same bucket: kept
    exporter.configure(CONFIG.model_copy(update={"flush_interval_ms": 60_000, "bucket": "other"}))
    assert exporter.status.pending == 0
