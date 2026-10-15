"""Conversion between Modbus 16-bit registers and typed engineering values.

Modbus only defines 16-bit registers transmitted big-endian ("AB"). Wider types
span consecutive registers and every vendor picks its own byte layout, so we
name the layout by the position of the bytes A (most significant) .. D:

    ABCD  big-endian                      registers [AB, CD]
    CDAB  word swap                       registers [CD, AB]
    BADC  byte swap inside each word      registers [BA, DC]
    DCBA  little-endian                   registers [DC, BA]

The same two operations (reverse word order, swap bytes in each word) are
applied to 64-bit values, and the byte swap alone is applied to 16-bit values.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class CodecError(ValueError):
    """Raised when a value cannot be decoded from or encoded to registers."""


class DataType(str, Enum):
    INT16 = "int16"
    UINT16 = "uint16"
    HEX16 = "hex16"
    BIN16 = "bin16"
    INT32 = "int32"
    UINT32 = "uint32"
    FLOAT32 = "float32"
    INT64 = "int64"
    UINT64 = "uint64"
    FLOAT64 = "float64"


class ByteOrder(str, Enum):
    ABCD = "ABCD"
    CDAB = "CDAB"
    BADC = "BADC"
    DCBA = "DCBA"

    @property
    def swap_words(self) -> bool:
        return self in (ByteOrder.CDAB, ByteOrder.DCBA)

    @property
    def swap_bytes(self) -> bool:
        return self in (ByteOrder.BADC, ByteOrder.DCBA)


# struct format character and register count for each type.
_LAYOUT: dict[DataType, tuple[str, int]] = {
    DataType.INT16: ("h", 1),
    DataType.UINT16: ("H", 1),
    DataType.HEX16: ("H", 1),
    DataType.BIN16: ("H", 1),
    DataType.INT32: ("i", 2),
    DataType.UINT32: ("I", 2),
    DataType.FLOAT32: ("f", 2),
    DataType.INT64: ("q", 4),
    DataType.UINT64: ("Q", 4),
    DataType.FLOAT64: ("d", 4),
}

_FLOAT_TYPES = frozenset({DataType.FLOAT32, DataType.FLOAT64})
# Types shown as bit patterns: scale and unit do not apply to them.
_PATTERN_TYPES = frozenset({DataType.HEX16, DataType.BIN16})


def register_count(dtype: DataType) -> int:
    """Number of 16-bit registers occupied by ``dtype``."""
    return _LAYOUT[dtype][1]


def is_float(dtype: DataType) -> bool:
    return dtype in _FLOAT_TYPES


def _reorder(words: Sequence[int], order: ByteOrder) -> list[int]:
    """Convert between wire order and canonical big-endian order.

    Both operations are involutions and commute, so the same function maps
    wire -> canonical and canonical -> wire.
    """
    out = list(words)
    if order.swap_words:
        out.reverse()
    if order.swap_bytes:
        out = [((w & 0xFF) << 8) | (w >> 8) for w in out]
    return out


def decode(
    registers: Sequence[int], dtype: DataType, order: ByteOrder = ByteOrder.ABCD
) -> int | float:
    """Decode the raw value of ``dtype`` from the first registers of ``registers``."""
    fmt, count = _LAYOUT[dtype]
    if len(registers) < count:
        raise CodecError(f"{dtype.value} needs {count} registers, got {len(registers)}")
    words = registers[:count]
    for w in words:
        if not 0 <= w <= 0xFFFF:
            raise CodecError(f"register value out of range: {w}")
    raw = struct.pack(f">{count}H", *_reorder(words, order))
    value: int | float = struct.unpack(f">{fmt}", raw)[0]
    return value


def encode(value: int | float, dtype: DataType, order: ByteOrder = ByteOrder.ABCD) -> list[int]:
    """Encode a raw value of ``dtype`` into wire-ordered registers."""
    fmt, count = _LAYOUT[dtype]
    if dtype in _FLOAT_TYPES:
        packed_value: int | float = float(value)
    else:
        if isinstance(value, float):
            if not value.is_integer():
                raise CodecError(f"{dtype.value} requires an integer, got {value}")
            value = int(value)
        packed_value = value
    try:
        raw = struct.pack(f">{fmt}", packed_value)
    except (struct.error, OverflowError) as exc:
        raise CodecError(f"{value} does not fit in {dtype.value}") from exc
    return _reorder(list(struct.unpack(f">{count}H", raw)), order)


@dataclass(frozen=True)
class RegisterFormat:
    """How a register (or the group of registers starting at it) is presented."""

    dtype: DataType = DataType.INT16
    order: ByteOrder = ByteOrder.ABCD
    scale: float = 1.0
    unit: str = ""
    alias: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.scale) or self.scale == 0:
            raise CodecError("scale must be a finite, non-zero number")


def to_engineering(raw: int | float, fmt: RegisterFormat) -> int | float:
    """Apply the scale factor. Integers stay integers when the scale is 1."""
    if fmt.dtype in _PATTERN_TYPES or fmt.scale == 1:
        return raw
    return raw * fmt.scale


def from_engineering(value: int | float, fmt: RegisterFormat) -> list[int]:
    """Registers to write so that the device holds ``value`` in engineering units."""
    if fmt.dtype in _PATTERN_TYPES or fmt.scale == 1:
        raw: int | float = value
    else:
        raw = value / fmt.scale
    if not is_float(fmt.dtype) and isinstance(raw, float):
        if not math.isfinite(raw):
            raise CodecError(f"cannot write {value} to an integer register")
        raw = round(raw)
    return encode(raw, fmt.dtype, fmt.order)


def format_value(value: int | float, dtype: DataType, decimals: int | None = None) -> str:
    """Human-readable text for a decoded (and possibly scaled) value."""
    if dtype is DataType.HEX16:
        return f"0x{int(value):04X}"
    if dtype is DataType.BIN16:
        bits = f"{int(value):016b}"
        return " ".join(bits[i : i + 4] for i in range(0, 16, 4))
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        if decimals is not None:
            return f"{value:.{decimals}f}"
        return f"{value:.7g}" if dtype is not DataType.FLOAT64 else f"{value:.15g}"
    return str(value)


@dataclass(frozen=True)
class DecodedCell:
    """One cell of a polling table.

    A multi-register value is reported on its first address; the following
    addresses it covers are reported with ``covered_by`` pointing back to it.
    """

    address: int
    registers: tuple[int, ...]
    value: int | float | None
    text: str
    fmt: RegisterFormat
    covered_by: int | None = None
    error: str | None = None


def decode_table(
    registers: Sequence[int],
    start_address: int,
    formats: dict[int, RegisterFormat] | None = None,
    default: RegisterFormat | None = None,
) -> list[DecodedCell]:
    """Decode a block of registers into cells, honouring per-address formats."""
    formats = formats or {}
    default = default or RegisterFormat()
    cells: list[DecodedCell] = []
    i = 0
    while i < len(registers):
        address = start_address + i
        fmt = formats.get(address, default)
        count = register_count(fmt.dtype)
        words = tuple(registers[i : i + count])
        if len(words) < count:
            cells.append(
                DecodedCell(address, words, None, "-", fmt, error="incomplete: read more registers")
            )
            for j in range(1, len(words)):
                cells.append(
                    DecodedCell(address + j, (words[j],), None, "", fmt, covered_by=address)
                )
            break
        try:
            value = to_engineering(decode(words, fmt.dtype, fmt.order), fmt)
            cells.append(DecodedCell(address, words, value, format_value(value, fmt.dtype), fmt))
        except CodecError as exc:
            cells.append(DecodedCell(address, words, None, "-", fmt, error=str(exc)))
        for j in range(1, count):
            cells.append(DecodedCell(address + j, (words[j],), None, "", fmt, covered_by=address))
        i += count
    return cells
