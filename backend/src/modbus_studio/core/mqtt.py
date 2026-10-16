"""MQTT exporter: every polled value as a JSON message on its own topic.

Polling never waits for the broker. ``offer()`` only formats the messages and
appends them to a bounded buffer; a background task hands them to the MQTT client
while it is connected. The client (paho-mqtt) runs its network loop in a thread of
its own and connects and reconnects by itself, waiting 1 s to 30 s between tries.
While the broker is down the buffer fills and then drops its oldest messages, and
the status says so.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import secrets
import socket
import ssl
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion, MQTTErrorCode, MQTTProtocolVersion

from ..models.exporters import ExporterStatus, ExporterTest, MQTTConfig
from .influx import Sample

log = logging.getLogger(__name__)

RECONNECT_MIN_S = 1
RECONNECT_MAX_S = 30
# Messages handed to the client and not yet written (QoS 0) or acknowledged (QoS 1
# and 2). Beyond it they wait in the exporter's own bounded buffer.
MAX_IN_CLIENT = 1000
# At shutdown, try to send what is left for at most this long.
CLOSE_FLUSH_S = 2.0

# Characters that cannot appear inside one level of a topic.
_LEVEL_TABLE = str.maketrans({"/": "_", "+": "_", "#": "_", "\0": "_"})


def _level(text: str) -> str:
    return text.translate(_LEVEL_TABLE)


def topic_for(template: str, sample: Sample) -> str:
    """The topic of a sample. Values never add levels: a "/" in a name becomes "_"."""
    fields = {
        "connection": sample.connection,
        "device": str(sample.device),
        "window": sample.window,
        "alias": sample.alias or str(sample.address),
        "address": str(sample.address),
        "unit": sample.unit,
    }
    return template.format(**{k: _level(v) for k, v in fields.items()})


def payload_for(sample: Sample) -> bytes | None:
    """The JSON payload of a sample, or None if JSON cannot carry its value."""
    value: float | int | bool = sample.value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None  # JSON has no NaN or infinity
        # 15 significant digits drop the noise of scaling (1153 * 0.1 = 115.30000000000001).
        value = float(f"{value:.15g}")
    stamp = datetime.fromtimestamp(sample.timestamp, tz=timezone.utc)
    body = {
        "value": value,
        "unit": sample.unit,
        "timestamp": stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "alias": sample.alias,
        "address": sample.address,
        "device": sample.device,
        "connection": sample.connection,
        "window": sample.window,
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def describe_error(exc: BaseException, host: str, port: int) -> str:
    where = f"{host}:{port}"
    if isinstance(exc, ssl.SSLCertVerificationError):
        return f"TLS: certificate of {where} not accepted: {exc.verify_message}"
    if isinstance(exc, ssl.SSLError):
        return f"TLS error with {where}: {getattr(exc, 'reason', None) or exc}"
    if isinstance(exc, ConnectionRefusedError):
        return f"cannot connect to {where}: connection refused"
    if isinstance(exc, socket.gaierror):
        return f"cannot connect to {where}: unknown host ({exc.strerror or exc})"
    if isinstance(exc, TimeoutError):
        return f"no answer from {where} (timeout)"
    return f"cannot connect to {where}: {exc}"


def ssl_context(cfg: MQTTConfig) -> ssl.SSLContext:
    """The TLS context for ``cfg``. Raises OSError/ssl.SSLError on unreadable files."""
    for name in ("ca_file", "cert_file", "key_file"):
        path = getattr(cfg, name)
        if path and not os.path.isfile(path):
            raise FileNotFoundError(f"{name} {path!r} not found on the server")
    context = ssl.create_default_context(cafile=cfg.ca_file or None)
    if cfg.cert_file:
        context.load_cert_chain(cfg.cert_file, cfg.key_file or None)
    if not cfg.verify_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _prepare(client: mqtt.Client, cfg: MQTTConfig) -> None:
    """Credentials and TLS. Raises OSError or ValueError on unusable TLS files."""
    if cfg.username:
        client.username_pw_set(cfg.username, cfg.password or None)
    if cfg.tls:
        client.tls_set_context(ssl_context(cfg))
        if not cfg.verify_tls:
            client.tls_insecure_set(True)


def test_connection(cfg: MQTTConfig, client_id: str, timeout: float = 5.0) -> ExporterTest:
    """Connect once with the settings, wait for the broker's answer and disconnect.
    Blocking: run it in a thread."""
    started = time.monotonic()
    where = f"{cfg.host}:{cfg.port}"

    def result(ok: bool, message: str) -> ExporterTest:
        elapsed = round((time.monotonic() - started) * 1000, 1)
        return ExporterTest(ok=ok, message=message, elapsed_ms=elapsed)

    if missing := cfg.missing():
        return result(False, f"missing: {', '.join(missing)}")
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=MQTTProtocolVersion.MQTTv311,
        clean_session=True,
    )
    client.connect_timeout = timeout
    try:
        _prepare(client, cfg)
    except (OSError, ValueError) as exc:
        return result(False, f"TLS settings: {exc}")
    answer: list[Any] = []
    done = threading.Event()

    def on_connect(_c: Any, _u: Any, _f: Any, reason: Any, _p: Any) -> None:
        answer.append(reason)
        done.set()

    client.on_connect = on_connect
    client.on_disconnect = lambda *_: done.set()
    try:
        client.connect(cfg.host, cfg.port, cfg.keepalive_s)
    except OSError as exc:
        return result(False, describe_error(exc, cfg.host, cfg.port))
    client.loop_start()
    try:
        closed = done.wait(timeout)
    finally:
        client.disconnect()
        client.loop_stop()
    if not answer:
        if closed:
            return result(
                False,
                f"{where} closed the connection before accepting it: "
                "check the port and the TLS setting",
            )
        return result(False, f"no answer from {where} within {timeout:g} s")
    if answer[0].is_failure:
        return result(False, f"connection refused by the broker: {answer[0]}")
    return result(True, f"connected to {where}" + (" with TLS" if cfg.tls else ""))


class _Client(mqtt.Client):
    """paho's client, reporting why a connection attempt failed (paho only says that
    it did)."""

    def __init__(self, on_connect_error: Callable[[OSError], None], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._on_connect_error = on_connect_error

    def reconnect(self) -> MQTTErrorCode:
        try:
            return super().reconnect()
        except OSError as exc:
            self._on_connect_error(exc)
            raise


class MqttExporter:
    def __init__(self) -> None:
        self.config = MQTTConfig()
        self.status = ExporterStatus(connected=False)
        self._buffer: deque[tuple[str, bytes]] = deque(maxlen=self.config.buffer_size)
        self._client: _Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._in_client = 0
        # Whether the broker answered the current connection attempt (CONNACK).
        self._answered = False
        # Callbacks of a client that has been replaced are ignored.
        self._generation = 0
        self.default_client_id = f"modbus-studio-{secrets.token_hex(4)}"

    # -- configuration -----------------------------------------------------

    @property
    def active(self) -> bool:
        return self.config.enabled and not self.config.missing()

    def configure(self, config: MQTTConfig) -> None:
        """Apply new settings and reconnect with them. Messages not yet sent are kept
        unless the broker or the topic changed."""
        old = self.config
        if (config.host, config.port, config.topic) != (old.host, old.port, old.topic):
            self._buffer.clear()
        self.config = config
        self._buffer = deque(self._buffer, maxlen=config.buffer_size)
        self._stop_client()
        self.status = self.status.model_copy(
            update={
                "state": self._idle_state(),
                "last_error": None,
                "last_error_at": None,
                "pending": len(self._buffer),
                "connected": False,
            }
        )
        if self.active:
            self._start_client()

    def _idle_state(self) -> str:
        if not self.config.enabled:
            return "disabled"
        return "incomplete" if self.config.missing() else "idle"

    def _start_client(self) -> None:
        cfg = self.config
        self._loop = asyncio.get_running_loop()
        generation = self._generation
        client = _Client(
            on_connect_error=lambda exc: self._from_thread(self._connect_failed, generation, exc),
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=cfg.client_id or self.default_client_id,
            protocol=MQTTProtocolVersion.MQTTv311,
            clean_session=True,
        )
        try:
            _prepare(client, cfg)
        except (OSError, ValueError) as exc:
            self._failed(f"TLS settings: {exc}")
            return
        client.reconnect_delay_set(RECONNECT_MIN_S, RECONNECT_MAX_S)
        client.on_connect = lambda _c, _u, _f, rc, _p: self._from_thread(
            self._connected, generation, rc
        )
        client.on_disconnect = lambda _c, _u, _f, rc, _p: self._from_thread(
            self._disconnected, generation, rc
        )
        client.on_publish = lambda _c, _u, _mid, _rc, _p: self._from_thread(
            self._published, generation
        )
        client.connect_async(cfg.host, cfg.port, cfg.keepalive_s)
        client.loop_start()
        self._client = client
        self._task = asyncio.create_task(self._run(), name="mqtt-exporter")

    def _stop_client(self) -> None:
        """Drop the current client without waiting for its thread to end."""
        self._generation += 1
        if self._task is not None:
            self._task.cancel()
            self._task = None
        client, self._client = self._client, None
        self._in_client = 0
        if client is not None:
            client.disconnect()
            # loop_stop() joins the network thread, which may be inside a connection
            # attempt for a few seconds: never on the event loop.
            threading.Thread(target=client.loop_stop, daemon=True).start()

    async def close(self) -> None:
        """Disconnect after one last attempt to send what is buffered."""
        client = self._client
        if client is None:
            return
        deadline = time.monotonic() + CLOSE_FLUSH_S
        while (self._buffer or self._in_client) and self.status.connected:
            if time.monotonic() > deadline:
                break
            self._drain()
            await asyncio.sleep(0.02)
        self._generation += 1
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._client = None
        client.disconnect()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.to_thread(client.loop_stop), CLOSE_FLUSH_S)
        self.status.connected = False

    # -- data in -----------------------------------------------------------

    def offer(self, samples: Iterable[Sample]) -> None:
        """Queue samples for publishing. Never blocks and never raises."""
        if not self.active:
            return
        topic = self.config.topic
        for sample in samples:
            if self.config.aliased_only and not sample.alias:
                continue
            payload = payload_for(sample)
            if payload is None:
                continue
            if len(self._buffer) == self._buffer.maxlen:
                self.status.dropped += 1
            self._buffer.append((topic_for(topic, sample), payload))
        self.status.pending = len(self._buffer)
        self._wake.set()

    # -- data out ----------------------------------------------------------

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            self._drain()

    def _drain(self) -> None:
        """Hand buffered messages to the client while it is connected."""
        client, cfg = self._client, self.config
        while (
            client is not None
            and self._buffer
            and self.status.connected
            and self._in_client < MAX_IN_CLIENT
        ):
            topic, payload = self._buffer[0]
            info = client.publish(topic, payload, qos=cfg.qos, retain=cfg.retain)
            if info.rc == MQTTErrorCode.MQTT_ERR_SUCCESS:
                self._buffer.popleft()
                self._in_client += 1
            elif info.rc == MQTTErrorCode.MQTT_ERR_NO_CONN:
                break  # kept; sent after the reconnection
            else:
                self._buffer.popleft()
                self.status.dropped += 1
                self._failed(f"publish to {topic!r} failed: {mqtt.error_string(info.rc)}")
        self.status.pending = len(self._buffer)

    # -- events from the client's thread -----------------------------------

    def _from_thread(self, callback: Callable[..., None], *args: Any) -> None:
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):  # the loop is closed: shutting down
            loop.call_soon_threadsafe(callback, *args)

    def _connected(self, generation: int, reason: Any) -> None:
        if generation != self._generation:
            return
        self._answered = True
        if reason.is_failure:
            self.status.connected = False
            self._failed(f"connection refused by the broker: {reason}")
            return
        self.status.connected = True
        self.status.state = "ok"
        self.status.last_success_at = time.time()
        log.info("MQTT export: connected to %s:%s", self.config.host, self.config.port)
        self._wake.set()

    def _disconnected(self, generation: int, reason: Any) -> None:
        if generation != self._generation:
            return
        was_connected = self.status.connected
        self.status.connected = False
        if self.config.qos == 0:
            # Messages the client had not written yet are gone with the connection.
            self.status.dropped += self._in_client
            self._in_client = 0
        answered, self._answered = self._answered, False
        where = f"{self.config.host}:{self.config.port}"
        if was_connected:
            self._failed(f"disconnected from {where}: {reason}")
        elif not answered:
            # Closed before the broker answered CONNECT: often TLS on one side only.
            self._failed(
                f"{where} closed the connection before accepting it ({reason}): "
                "check the port and the TLS setting"
            )

    def _connect_failed(self, generation: int, exc: OSError) -> None:
        if generation != self._generation:
            return
        self.status.connected = False
        self._failed(describe_error(exc, self.config.host, self.config.port))

    def _published(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._in_client = max(0, self._in_client - 1)
        self.status.points_sent += 1
        self.status.writes += 1
        self.status.last_success_at = time.time()
        if self._buffer:
            self._wake.set()

    def _failed(self, message: str) -> None:
        if self.status.last_error != message:
            log.warning("MQTT export: %s", message)
        self.status.errors += 1
        self.status.state = "error"
        self.status.last_error = message
        self.status.last_error_at = time.time()
