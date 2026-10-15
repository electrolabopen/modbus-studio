"""Read models returned by the API and pushed over the WebSocket."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..core.codec import ByteOrder, DataType
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


class SerialPortView(BaseModel):
    """A serial port the OS reports, for picking one in an RTU connection."""

    device: str
    description: str = ""
    manufacturer: str | None = None
    serial_number: str | None = None
    vid: int | None = None
    pid: int | None = None
    # /dev/serial/by-id/... (Linux, USB adapters): survives replugging, unlike ttyUSB0.
    stable_path: str | None = None
    # Connections configured with this port (by device name or stable path).
    used_by: list[str] = []


class TrafficEntryView(BaseModel):
    seq: int
    timestamp: float
    connection_id: str
    direction: Literal["tx", "rx"]
    hex: str
    # What the monitor can tell from the frame header (None when it cannot).
    device_id: int | None = None
    function: int | None = None
    exception_code: int | None = None
    transaction_id: int | None = None
    # A problem with the frame itself (bad CRC, wrong MBAP length, too short).
    error: str | None = None


class WindowWrite(BaseModel):
    """Write one cell of a polling window, in engineering units."""

    address: int = Field(ge=0, le=0xFFFF)
    value: bool | int | float
    # Use FC15/FC16 even for a single coil/register (some devices lack FC05/FC06).
    force_multiple: bool = False


class FormatPatch(BaseModel):
    """Change how the cells ``start``..``end`` (inclusive) of a window are displayed.

    Fields left out keep each cell's current value, so a range can get a new unit
    without losing per-cell data types. ``reset`` returns the range to the window's
    default format.
    """

    start: int = Field(ge=0, le=0xFFFF)
    end: int = Field(ge=0, le=0xFFFF)
    dtype: DataType | None = None
    order: ByteOrder | None = None
    scale: float | None = None
    unit: str | None = Field(default=None, max_length=32)
    alias: str | None = Field(default=None, max_length=64)
    reset: bool = False

    @model_validator(mode="after")
    def _check(self) -> FormatPatch:
        if self.end < self.start:
            raise ValueError("end must not be before start")
        if self.scale is not None and (not math.isfinite(self.scale) or self.scale == 0):
            raise ValueError("scale must be a finite, non-zero number")
        if self.alias is not None and self.end != self.start:
            raise ValueError("an alias names one cell: start and end must be equal")
        return self


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


class RegisterMapImport(BaseModel):
    """A CSV register map, see ``core.registermap`` for the format."""

    csv: str = Field(max_length=1_000_000)


class WorkspaceImportResult(BaseModel):
    connections: int
    polls: int


class WriteLogEntry(BaseModel):
    """One write sent to a device (or attempted), as kept in the write log."""

    seq: int
    timestamp: float
    connection_id: str
    connection_name: str = ""
    device_id: int
    function: Literal[5, 6, 15, 16]
    address: int
    # Window the write came from; None for raw writes through the API.
    poll_id: str | None = None
    alias: str = ""
    unit: str = ""
    # Value shown by the window before the write (its last poll); None if unknown.
    old: str | None = None
    new: str
    # Coil states or registers exactly as sent.
    values: list[int]
    ok: bool
    error: str | None = None


class RawWrite(BaseModel):
    device_id: int = Field(default=1, ge=0, le=255)
    function: Literal[5, 6, 15, 16]
    address: int = Field(ge=0, le=0xFFFF)
    values: list[int] = Field(min_length=1, max_length=1968)
