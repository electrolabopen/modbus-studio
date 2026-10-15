"""Read models returned by the API and pushed over the WebSocket."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .connection import ConnectionConfig
from .poll import PollDefinition


class Cell(BaseModel):
    address: int
    # Engineering value (bool for coils / discrete inputs). None for the
    # continuation registers of a multi-register value and for decode errors.
    value: int | float | bool | None
    text: str
    raw: list[int]
    alias: str = ""
    unit: str = ""
    covered_by: int | None = None
    error: str | None = None


class PollData(BaseModel):
    poll_id: str
    seq: int
    timestamp: float
    duration_ms: float
    ok: bool
    error_kind: str | None = None
    error: str | None = None
    exception_code: int | None = None
    stats: dict[str, int]
    # Empty when the read failed: clients keep showing the previous values.
    cells: list[Cell] = Field(default_factory=list)


class PollView(BaseModel):
    definition: PollDefinition
    running: bool
    stats: dict[str, int]
    data: PollData | None = None


class ConnectionView(BaseModel):
    config: ConnectionConfig
    state: str
    stats: dict[str, int]
    last_error: str | None = None


class TrafficEntryView(BaseModel):
    seq: int
    timestamp: float
    connection_id: str
    direction: Literal["tx", "rx"]
    hex: str


class WindowWrite(BaseModel):
    """Write one cell of a polling window, in engineering units."""

    address: int = Field(ge=0, le=0xFFFF)
    value: bool | int | float
    # Use FC15/FC16 even for a single coil/register (some devices lack FC05/FC06).
    force_multiple: bool = False


class WritePlan(BaseModel):
    """What a window write sends to the device, shown to the user before confirming."""

    poll_id: str
    connection_id: str
    device_id: int
    function: Literal[5, 6, 15, 16]
    address: int
    # Coil states (0/1) or registers in wire order, exactly as sent.
    values: list[int]
    requested: bool | int | float
    # Engineering value the device will hold once the request is encoded: it differs
    # from ``requested`` when the raw type cannot represent it (scale, integer rounding).
    result: bool | int | float
    text: str
    rounded: bool = False
    unit: str = ""
    dtype: str | None = None
    order: str | None = None
    scale: float | None = None


class RawWrite(BaseModel):
    device_id: int = Field(default=1, ge=0, le=255)
    function: Literal[5, 6, 15, 16]
    address: int = Field(ge=0, le=0xFFFF)
    values: list[int] = Field(min_length=1, max_length=1968)
