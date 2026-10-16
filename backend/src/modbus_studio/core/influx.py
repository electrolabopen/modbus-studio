"""InfluxDB 2.x exporter: polled values as line protocol, written in batches.

Polling never waits for InfluxDB. ``offer()`` only formats the points and appends
them to a bounded buffer; a background task writes the buffer with the HTTP API
(``POST /api/v2/write``). While InfluxDB is slow or down the buffer fills and then
drops its oldest points, and the status says so.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from ..models.exporters import ExporterStatus, ExporterTest, InfluxDBConfig

log = logging.getLogger(__name__)

# After a failed write, wait this long before the next try, doubling up to the max.
RETRY_MIN_S = 1.0
RETRY_MAX_S = 30.0
# At shutdown, try to write what is left for at most this long.
CLOSE_FLUSH_S = 2.0


@dataclass(frozen=True)
class Sample:
    """One engineering value from a poll, with where it came from."""

    window: str
    connection: str
    device: int
    address: int
    alias: str
    unit: str
    value: float | int | bool
    timestamp: float  # seconds since the epoch


def _escape(text: str, specials: str) -> str:
    # Line protocol has no way to write a newline inside a name or tag value.
    text = text.replace("\r", " ").replace("\n", " ")
    for ch in "\\" + specials:
        text = text.replace(ch, "\\" + ch)
    return text


def measurement(text: str) -> str:
    return _escape(text, ", ")


def tag(text: str) -> str:
    return _escape(text, ",= ")


def to_line(sample: Sample) -> str | None:
    """The sample as one line of line protocol, or None if it cannot be written."""
    value = sample.value
    if isinstance(value, bool):
        field = "true" if value else "false"
    else:
        number = float(value)
        if not math.isfinite(number):
            return None  # InfluxDB has no NaN or infinity
        # Always a float: a register whose scale changes from 1 to 0.1 must keep
        # the same field type, or InfluxDB rejects every later point.
        # 15 significant digits drop the noise of scaling (1153 * 0.1 = 115.30000000000001).
        field = repr(float(f"{number:.15g}"))
    tags = {
        "connection": sample.connection,
        "device": str(sample.device),
        "alias": sample.alias or str(sample.address),
        "address": str(sample.address),
        "unit": sample.unit,
    }
    # Tags sorted by key, as InfluxDB recommends; empty tag values are not allowed.
    tag_text = "".join(f",{k}={tag(v)}" for k, v in sorted(tags.items()) if v)
    ns = round(sample.timestamp * 1e9)
    return f"{measurement(sample.window)}{tag_text} value={field} {ns}"


def describe_error(exc: Exception, url: str) -> str:
    if isinstance(exc, httpx.ConnectError):
        return f"cannot connect to {url}: {exc}" if str(exc) else f"cannot connect to {url}"
    if isinstance(exc, httpx.TimeoutException):
        return f"no answer from {url} (timeout)"
    return f"{type(exc).__name__}: {exc}"


def describe_response(response: httpx.Response) -> str:
    try:
        message = str(response.json().get("message", "")).strip()
    except ValueError:
        message = response.text.strip()[:200]
    hint = {
        401: "unauthorized: check the token",
        403: "forbidden: the token cannot write to this bucket",
        404: "not found: check the org and the bucket",
    }.get(response.status_code, f"HTTP {response.status_code}")
    return f"{hint} ({message})" if message else hint


def _client(cfg: InfluxDBConfig, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=cfg.url,
        headers={
            "Authorization": f"Token {cfg.token}",
            "Content-Type": "text/plain; charset=utf-8",
        },
        timeout=cfg.timeout_s,
        verify=cfg.verify_tls,
        transport=transport,
    )


async def test_connection(
    cfg: InfluxDBConfig, transport: httpx.AsyncBaseTransport | None = None
) -> ExporterTest:
    """Try the settings with an empty write: InfluxDB checks the token, the org and
    the bucket and answers 204 without storing anything."""
    started = time.monotonic()

    def result(ok: bool, message: str) -> ExporterTest:
        elapsed = round((time.monotonic() - started) * 1000, 1)
        return ExporterTest(ok=ok, message=message, elapsed_ms=elapsed)

    if missing := cfg.missing():
        return result(False, f"missing: {', '.join(missing)}")
    try:
        async with _client(cfg, transport) as client:
            response = await client.post(
                "/api/v2/write",
                params={"org": cfg.org, "bucket": cfg.bucket, "precision": "ns"},
                content=b"",
            )
    except httpx.HTTPError as exc:
        return result(False, describe_error(exc, cfg.url))
    if response.status_code != 204:
        return result(False, describe_response(response))
    version = response.headers.get("X-Influxdb-Version")
    server = f"InfluxDB {version}" if version else "InfluxDB"
    return result(True, f"{server} accepts writes to bucket {cfg.bucket!r} of org {cfg.org!r}")


class InfluxExporter:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = InfluxDBConfig()
        self.status = ExporterStatus()
        self._buffer: deque[str] = deque(maxlen=self.config.buffer_size)
        self._transport = transport  # tests replace the network
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    # -- configuration -----------------------------------------------------

    @property
    def active(self) -> bool:
        return self.config.enabled and not self.config.missing()

    def configure(self, config: InfluxDBConfig) -> None:
        """Apply new settings; the sender restarts with them. Points not yet sent are
        kept unless the destination changed."""
        destination = (config.url, config.org, config.bucket)
        if destination != (self.config.url, self.config.org, self.config.bucket):
            self._buffer.clear()
        self.config = config
        self._buffer = deque(self._buffer, maxlen=config.buffer_size)
        self.status = self.status.model_copy(
            update={
                "state": self._idle_state(),
                "last_error": None,
                "last_error_at": None,
                "pending": len(self._buffer),
            }
        )
        self._restart()

    def _idle_state(self) -> str:
        if not self.config.enabled:
            return "disabled"
        return "incomplete" if self.config.missing() else "idle"

    def _restart(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self.active:
            self._task = asyncio.create_task(self._run(), name="influxdb-exporter")

    async def close(self) -> None:
        """Stop the sender after one last attempt to write what is buffered."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if self._buffer:
            with contextlib.suppress(Exception):
                async with self._client() as client:
                    # Bounded: a dead server must not hold up shutting down.
                    await asyncio.wait_for(self._write_once(client), CLOSE_FLUSH_S)

    # -- data in -----------------------------------------------------------

    def offer(self, samples: Iterable[Sample]) -> None:
        """Queue samples for writing. Never blocks and never raises."""
        if not self.active:
            return
        for sample in samples:
            if self.config.aliased_only and not sample.alias:
                continue
            line = to_line(sample)
            if line is None:
                continue
            if len(self._buffer) == self._buffer.maxlen:
                self.status.dropped += 1
            self._buffer.append(line)
        self.status.pending = len(self._buffer)
        if len(self._buffer) >= self.config.batch_size:
            self._wake.set()

    # -- data out ----------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        return _client(self.config, self._transport)

    async def _run(self) -> None:
        retry = RETRY_MIN_S
        async with self._client() as client:
            while True:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self.config.flush_interval_ms / 1000)
                self._wake.clear()
                # Write everything buffered, batch by batch, until empty or failing.
                while self._buffer:
                    if await self._write_once(client):
                        retry = RETRY_MIN_S
                        continue
                    await asyncio.sleep(retry)
                    retry = min(retry * 2, RETRY_MAX_S)
                    break

    async def _write_once(self, client: httpx.AsyncClient) -> bool:
        """Write the oldest batch. True when it left the buffer (sent or dropped)."""
        cfg = self.config
        batch = [self._buffer[i] for i in range(min(cfg.batch_size, len(self._buffer)))]
        try:
            response = await client.post(
                "/api/v2/write",
                params={"org": cfg.org, "bucket": cfg.bucket, "precision": "ns"},
                content="\n".join(batch).encode(),
            )
        except httpx.HTTPError as exc:
            self._failed(describe_error(exc, cfg.url))
            return False
        if response.status_code == 204:
            self._take(len(batch))
            self.status.points_sent += len(batch)
            self.status.writes += 1
            self.status.state = "ok"
            self.status.last_success_at = time.time()
            return True
        message = describe_response(response)
        if response.status_code in (400, 413, 422):
            # Retrying the same points cannot work: drop them, keep the rest flowing.
            self._take(len(batch))
            self.status.dropped += len(batch)
            self._failed(f"{message}; {len(batch)} points dropped")
            return True
        self._failed(message)
        return False

    def _take(self, count: int) -> None:
        for _ in range(count):
            self._buffer.popleft()
        self.status.pending = len(self._buffer)

    def _failed(self, message: str) -> None:
        if self.status.last_error != message:
            log.warning("InfluxDB export: %s", message)
        self.status.errors += 1
        self.status.state = "error"
        self.status.last_error = message
        self.status.last_error_at = time.time()
