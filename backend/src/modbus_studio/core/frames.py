"""Describe captured frames for the traffic monitor (no full PDU decoding).

Modbus TCP (MBAP header):  transaction(2) protocol(2) length(2) unit(1) function(1) data
Modbus RTU / RTU over TCP: address(1) function(1) data CRC(2, low byte first)

An exception response has the function code with bit 7 set, followed by the
exception code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Framing = Literal["tcp", "rtu"]

MBAP_LENGTH = 7


@dataclass(frozen=True)
class FrameInfo:
    device_id: int | None = None
    function: int | None = None  # without the exception bit
    exception_code: int | None = None
    transaction_id: int | None = None
    # A problem with the frame itself: bad CRC, wrong MBAP length, too short.
    error: str | None = None


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS (polynomial 0xA001 reflected, initial value 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _pdu(function_byte: int, rest: bytes) -> tuple[int, int | None]:
    if function_byte & 0x80:
        return function_byte & 0x7F, rest[0] if rest else None
    return function_byte, None


def describe(data: bytes, framing: Framing) -> FrameInfo:
    if framing == "tcp":
        if len(data) < MBAP_LENGTH + 1:
            return FrameInfo(error=f"short frame ({len(data)} bytes)")
        transaction = int.from_bytes(data[0:2], "big")
        length = int.from_bytes(data[4:6], "big")
        function, exception = _pdu(data[7], data[8:])
        error = None
        if length != len(data) - 6:
            error = f"MBAP length {length}, frame carries {len(data) - 6}"
        elif data[2:4] != b"\x00\x00":
            error = "protocol id is not 0"
        return FrameInfo(data[6], function, exception, transaction, error)

    if len(data) < 4:
        return FrameInfo(error=f"short frame ({len(data)} bytes)")
    function, exception = _pdu(data[1], data[2:-2])
    expected = crc16(data[:-2])
    received = int.from_bytes(data[-2:], "little")
    error = None if expected == received else f"bad CRC {received:04X}, expected {expected:04X}"
    return FrameInfo(data[0], function, exception, None, error)
