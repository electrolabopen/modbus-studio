"""Settings of the exporters that send polled values to other systems."""

from __future__ import annotations

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
    # sent yet; ok: the last write succeeded; error: the last write failed.
    state: Literal["disabled", "incomplete", "idle", "ok", "error"] = "disabled"
    last_error: str | None = None
    last_error_at: float | None = None
    last_success_at: float | None = None
    points_sent: int = 0
    writes: int = 0
    errors: int = 0
    # Points discarded: buffer full, or rejected by the server as malformed.
    dropped: int = 0
    pending: int = 0


class InfluxDBView(BaseModel):
    config: InfluxDBConfigView
    status: ExporterStatus


class ExportersConfig(BaseModel):
    influxdb: InfluxDBConfig = Field(default_factory=InfluxDBConfig)

    def without_secrets(self) -> ExportersConfig:
        return self.model_copy(
            update={"influxdb": self.influxdb.model_copy(update={"token": None})}
        )
