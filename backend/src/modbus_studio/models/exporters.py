"""Settings of the exporters that send polled values to other systems."""

from __future__ import annotations

import string
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class InfluxDBConfig(BaseModel):
    """Write every polled value to an InfluxDB 2.x bucket.

    One point per value: the measurement is the window's name, the tags are
    ``connection``, ``device``, ``alias`` (the address when there is none),
    ``address`` and ``unit``, and the field ``value`` holds the engineering value.
    """

    enabled: bool = False
    url: str = Field(default="http://localhost:8086", examples=["http://influxdb:8086"])
    org: str = ""
    bucket: str = ""
    # API token with write access to the bucket. Never returned by the API: GET
    # responses only say whether one is set, and a PUT without it keeps the current one.
    token: str | None = None
    # Only export registers that have an alias.
    aliased_only: bool = False
    # Points are collected and written in batches at most this often.
    flush_interval_ms: int = Field(default=1000, ge=100, le=60_000)
    batch_size: int = Field(default=5000, ge=1, le=50_000)
    # Points kept while InfluxDB is unreachable; the oldest are dropped beyond it.
    buffer_size: int = Field(default=100_000, ge=100, le=10_000_000)
    timeout_s: float = Field(default=5.0, gt=0, le=60)
    verify_tls: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value

    def missing(self) -> list[str]:
        """Settings needed before anything can be written."""
        return [name for name in ("org", "bucket", "token") if not getattr(self, name)]


class InfluxDBConfigView(BaseModel):
    """An InfluxDB configuration as returned by the API: the token is withheld."""

    enabled: bool
    url: str
    org: str
    bucket: str
    token_set: bool
    aliased_only: bool
    flush_interval_ms: int
    batch_size: int
    buffer_size: int
    timeout_s: float
    verify_tls: bool

    @classmethod
    def of(cls, config: InfluxDBConfig) -> InfluxDBConfigView:
        return cls(
            **config.model_dump(exclude={"token"}),
            token_set=bool(config.token),
        )


class ExporterStatus(BaseModel):
    # disabled: switched off; incomplete: enabled but missing settings; idle: nothing
    # sent yet (MQTT: connecting); ok: the last write succeeded (MQTT: connected);
    # error: the last write failed (MQTT: not connected, see last_error).
    state: Literal["disabled", "incomplete", "idle", "ok", "error"] = "disabled"
    last_error: str | None = None
    last_error_at: float | None = None
    last_success_at: float | None = None
    points_sent: int = 0
    # InfluxDB: write requests. MQTT: messages, one per value.
    writes: int = 0
    errors: int = 0
    # Points discarded: buffer full, or rejected by the server as malformed.
    dropped: int = 0
    pending: int = 0
    # MQTT only: whether the client is connected to the broker.
    connected: bool | None = None


class InfluxDBView(BaseModel):
    config: InfluxDBConfigView
    status: ExporterStatus


# Placeholders a topic template may use.
TOPIC_FIELDS = ("connection", "device", "window", "alias", "address", "unit")


class MQTTConfig(BaseModel):
    """Publish every polled value to an MQTT broker, one message per value.

    The topic comes from ``topic``, a template with the placeholders in
    ``TOPIC_FIELDS``; the payload is JSON with the value, its unit and a timestamp.
    """

    enabled: bool = False
    host: str = Field(default="localhost", examples=["mosquitto"])
    port: int = Field(default=1883, ge=1, le=65535)
    # Empty: "modbus-studio-" plus a random suffix, chosen at startup.
    client_id: str = Field(default="", max_length=128)
    username: str = ""
    # Never returned by the API: GET responses only say whether one is set, and a PUT
    # without it keeps the current one.
    password: str | None = None
    topic: str = "modbus-studio/{connection}/{device}/{alias}"
    qos: Literal[0, 1, 2] = 0
    retain: bool = False
    # Only publish registers that have an alias.
    aliased_only: bool = False
    keepalive_s: int = Field(default=60, ge=5, le=3600)
    # Messages kept while the broker is unreachable; the oldest are dropped beyond it.
    buffer_size: int = Field(default=10_000, ge=100, le=1_000_000)
    tls: bool = False
    # PEM files, as paths on the server. Empty ca_file: the system's CA certificates.
    ca_file: str = ""
    cert_file: str = ""
    key_file: str = ""
    verify_tls: bool = True

    @field_validator("host")
    @classmethod
    def _check_host(cls, value: str) -> str:
        return value.strip()

    @field_validator("topic")
    @classmethod
    def _check_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic must not be empty")
        if "+" in value or "#" in value:
            raise ValueError("topic must not contain the wildcards + or #")
        if value.startswith("$"):
            raise ValueError("topics starting with $ are reserved for the broker")
        try:
            parts = list(string.Formatter().parse(value))
        except ValueError as exc:
            raise ValueError(f"topic: {exc}") from exc
        for _, name, spec, conversion in parts:
            if name is None:
                continue
            if name not in TOPIC_FIELDS:
                known = ", ".join("{" + f + "}" for f in TOPIC_FIELDS)
                raise ValueError(f"unknown placeholder {{{name}}} in topic; use {known}")
            if spec or conversion:
                raise ValueError(f"placeholder {{{name}}} takes no format")
        return value

    def missing(self) -> list[str]:
        """Settings needed before connecting."""
        return ["host"] if not self.host else []


class MQTTConfigView(BaseModel):
    """An MQTT configuration as returned by the API: the password is withheld."""

    enabled: bool
    host: str
    port: int
    client_id: str
    username: str
    password_set: bool
    topic: str
    qos: int
    retain: bool
    aliased_only: bool
    keepalive_s: int
    buffer_size: int
    tls: bool
    ca_file: str
    cert_file: str
    key_file: str
    verify_tls: bool

    @classmethod
    def of(cls, config: MQTTConfig) -> MQTTConfigView:
        return cls(
            **config.model_dump(exclude={"password"}),
            password_set=bool(config.password),
        )


class MQTTView(BaseModel):
    config: MQTTConfigView
    status: ExporterStatus


class ExportersView(BaseModel):
    influxdb: InfluxDBView
    mqtt: MQTTView


class ExporterTest(BaseModel):
    """The result of trying a set of exporter settings, without saving them."""

    ok: bool
    message: str
    elapsed_ms: float


class ExportersConfig(BaseModel):
    influxdb: InfluxDBConfig = Field(default_factory=InfluxDBConfig)
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)

    def without_secrets(self) -> ExportersConfig:
        return self.model_copy(
            update={
                "influxdb": self.influxdb.model_copy(update={"token": None}),
                "mqtt": self.mqtt.model_copy(update={"password": None}),
            }
        )
