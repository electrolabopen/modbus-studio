"""Register maps in CSV: one row per value, with how to display it.

    address,alias,type,byte_order,scale,unit
    0,counter,uint16,ABCD,1,
    2,temperature,int16,ABCD,0.1,°C
    10,flow,float32,CDAB,1,m3/h

- ``address`` is the 0-based protocol address (the one sent in the PDU) and is the
  only required column. Column order does not matter; headers are case-insensitive.
- Empty ``type``, ``byte_order``, ``scale`` and ``unit`` fall back to ``int16``,
  ``ABCD``, ``1`` and no unit.
- The delimiter may be ``,`` or ``;``. With ``;`` (what spreadsheets in many locales
  export) a decimal comma in ``scale`` is accepted too. Lines starting with ``#``
  are comments.

Every row is validated and all problems are reported by line number; nothing is
applied unless the whole file is valid.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

from .codec import ByteOrder, DataType, register_count

COLUMNS = ("address", "alias", "type", "byte_order", "scale", "unit")
MAX_ALIAS = 64
MAX_UNIT = 32


@dataclass(frozen=True)
class MapRow:
    line: int
    address: int
    alias: str
    dtype: DataType
    order: ByteOrder
    scale: float
    unit: str

    @property
    def last_address(self) -> int:
        return self.address + register_count(self.dtype) - 1


@dataclass(frozen=True)
class MapError:
    line: int
    message: str


@dataclass(frozen=True)
class WindowFit:
    """The smallest window, containing the current one, that holds every row."""

    address: int
    quantity: int


class RegisterMapError(ValueError):
    def __init__(self, errors: list[MapError], fit: WindowFit | None = None) -> None:
        super().__init__(f"{len(errors)} problem(s) in the register map")
        self.errors = errors
        # Set when resizing the window to ``fit`` would fix every problem.
        self.fit = fit


def _number(text: str, decimal_comma: bool) -> float:
    if decimal_comma:
        text = text.replace(",", ".")
    return float(text)


def parse_register_map(text: str) -> list[MapRow]:
    """Parse and check a CSV register map on its own (without a window)."""
    text = text.lstrip("﻿")
    lines = [(n, line) for n, line in enumerate(text.splitlines(), start=1)]
    content = [(n, line) for n, line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not content:
        raise RegisterMapError([MapError(1, "the file is empty")])

    header_line, header = content[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    reader = csv.reader(io.StringIO("\n".join(line for _, line in content)), delimiter=delimiter)
    rows = list(reader)
    names = [h.strip().lower() for h in rows[0]]
    errors: list[MapError] = []
    unknown = [n for n in names if n not in COLUMNS]
    if "address" not in names:
        errors.append(MapError(header_line, "missing the 'address' column"))
    if unknown:
        errors.append(
            MapError(
                header_line,
                f"unknown column(s) {', '.join(unknown)}; expected {', '.join(COLUMNS)}",
            )
        )
    if errors:
        raise RegisterMapError(errors)

    parsed: list[MapRow] = []
    if len(rows) != len(content):
        raise RegisterMapError([MapError(header_line, "quoted fields must not span lines")])
    for (line, _), values in zip(content[1:], rows[1:], strict=True):
        cell = {
            name: (values[i].strip() if i < len(values) else "") for i, name in enumerate(names)
        }
        if len(values) > len(names):
            errors.append(MapError(line, f"{len(values)} fields, the header has {len(names)}"))
            continue
        row_errors: list[str] = []
        try:
            address = int(cell["address"])
            if not 0 <= address <= 0xFFFF:
                raise ValueError
        except ValueError:
            row_errors.append(f"address {cell['address']!r} is not a number from 0 to 65535")
            address = -1
        try:
            dtype = DataType(cell.get("type", "").lower() or DataType.INT16.value)
        except ValueError:
            names_list = " ".join(t.value for t in DataType)
            row_errors.append(f"unknown type {cell['type']!r}; use one of: {names_list}")
            dtype = DataType.INT16
        try:
            order = ByteOrder(cell.get("byte_order", "").upper() or ByteOrder.ABCD.value)
        except ValueError:
            row_errors.append(
                f"unknown byte order {cell['byte_order']!r}; use ABCD, CDAB, BADC or DCBA"
            )
            order = ByteOrder.ABCD
        scale = 1.0
        if cell.get("scale"):
            try:
                scale = _number(cell["scale"], decimal_comma=delimiter == ";")
                if not math.isfinite(scale) or scale == 0:
                    raise ValueError
            except ValueError:
                row_errors.append(f"scale {cell['scale']!r} must be a non-zero number")
        alias, unit = cell.get("alias", ""), cell.get("unit", "")
        if len(alias) > MAX_ALIAS:
            row_errors.append(f"alias longer than {MAX_ALIAS} characters")
        if len(unit) > MAX_UNIT:
            row_errors.append(f"unit longer than {MAX_UNIT} characters")
        if row_errors:
            errors.extend(MapError(line, message) for message in row_errors)
        else:
            parsed.append(MapRow(line, address, alias, dtype, order, scale, unit))

    if not parsed and not errors:
        errors.append(MapError(header_line, "no rows after the header"))
    # Values must not overlap: a float32 at 10 also occupies 11.
    previous: MapRow | None = None
    for row in sorted(parsed, key=lambda r: r.address):
        if previous is not None and row.address <= previous.last_address:
            what = (
                "repeats address"
                if row.address == previous.address
                else f"overlaps the {previous.dtype.value} at {previous.address}"
                f" ({previous.address}-{previous.last_address})"
            )
            errors.append(
                MapError(row.line, f"address {row.address} {what} on line {previous.line}")
            )
            continue
        previous = row
    if errors:
        raise RegisterMapError(sorted(errors, key=lambda e: e.line))
    return parsed
