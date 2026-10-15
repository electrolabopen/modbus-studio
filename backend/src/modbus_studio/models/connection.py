"""Connection settings for the three supported transports."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .poll import new_id


class _ConnectionBase(BaseModel):
    id: str = Field(
        default_factory=new_id, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    name: str = ""
    timeout_s: float = Field(default=1.0, gt=0, le=60)
    retries: int = Field(default=0, ge=0, le=10)
    # Pause after each transaction. Some RTU devices and gateways need it.
    delay_between_requests_ms: int = Field(default=0, ge=0, le=60_000)
    # Reject every write (FC05/06/15/16) on this connection, e.g. on a live plant.
    read_only: bool = False


class TcpConnection(_ConnectionBase):
    """Modbus TCP: MBAP header, no CRC."""

    type: Literal["tcp"] = "tcp"
    host: str = Field(min_length=1)
    port: int = Field(default=502, ge=1, le=65535)


class RtuOverTcpConnection(_ConnectionBase):
    """RTU frames (with CRC) tunnelled over a raw TCP socket, as used by serial servers."""

    type: Literal["rtu_over_tcp"] = "rtu_over_tcp"
    host: str = Field(min_length=1)
    port: int = Field(default=502, ge=1, le=65535)


class RtuConnection(_ConnectionBase):
    """Modbus RTU over a serial line.

    Defaults follow the Modbus serial line specification (19200 baud, even parity).
    """

    type: Literal["rtu"] = "rtu"
    serial_port: str = Field(min_length=1, examples=["/dev/ttyUSB0", "COM3"])
    baudrate: int = Field(default=19200, gt=0)
    bytesize: Literal[7, 8] = 8
    parity: Literal["N", "E", "O"] = "E"
    stopbits: Literal[1, 2] = 1


ConnectionConfig = Annotated[
    TcpConnection | RtuOverTcpConnection | RtuConnection,
    Field(discriminator="type"),
]
