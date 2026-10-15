from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from ``MODBUS_STUDIO_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="MODBUS_STUDIO_", env_file=".env", extra="ignore")

    # Loopback by default: exposing the server on a plant network is an explicit decision.
    host: str = "127.0.0.1"
    port: int = 8000
    # When set, every API call must send "Authorization: Bearer <token>".
    token: str | None = None
    traffic_buffer: int = 5000
    # Workspace JSON loaded at startup (connections and windows), e.g. the compose demo.
    workspace: Path | None = None
    # Where the current workspace is saved after every change and restored at startup.
    # Once this file exists it wins over ``workspace``, which then only seeds a first run.
    state_file: Path | None = None
    # Append-only JSON Lines log of every write (time, device, address, old/new value).
    write_log_file: Path | None = None
    log_level: str = "info"

    @property
    def is_loopback(self) -> bool:
        return self.host in ("127.0.0.1", "::1", "localhost")


@lru_cache
def get_settings() -> Settings:
    return Settings()
