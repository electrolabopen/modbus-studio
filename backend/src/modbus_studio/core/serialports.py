"""Serial port discovery and readable reasons why a port does not open."""

from __future__ import annotations

import errno
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import serial
from serial.tools import list_ports

# udev links named after the adapter (vendor, model, serial number). Unlike
# /dev/ttyUSB0 they do not change when adapters are plugged in another order.
BY_ID = Path("/dev/serial/by-id")


@dataclass(frozen=True)
class SerialPort:
    device: str
    description: str
    manufacturer: str | None
    serial_number: str | None
    vid: int | None
    pid: int | None
    # /dev/serial/by-id/... for this device, when udev made one (Linux, USB).
    stable_path: str | None


def _stable_paths(by_id: Path = BY_ID) -> dict[str, str]:
    """Map each device (e.g. /dev/ttyUSB0) to its /dev/serial/by-id link."""
    links: dict[str, str] = {}
    try:
        entries = sorted(by_id.iterdir())
    except OSError:  # not Linux, or no USB serial adapter plugged in
        return links
    for link in entries:
        try:
            links.setdefault(os.path.realpath(link), str(link))
        except OSError:
            continue
    return links


def list_serial_ports(by_id: Path = BY_ID) -> list[SerialPort]:
    """Serial ports the OS reports, sorted by device name. Blocking: run in a thread."""
    stable = _stable_paths(by_id)
    ports = []
    for info in list_ports.comports():
        description = info.description if info.description not in (None, "n/a") else ""
        ports.append(
            SerialPort(
                device=info.device,
                description=description or "",
                manufacturer=info.manufacturer,
                serial_number=info.serial_number,
                vid=info.vid,
                pid=info.pid,
                stable_path=stable.get(os.path.realpath(info.device)),
            )
        )
    return sorted(ports, key=lambda p: _natural_key(p.device))


def _natural_key(device: str) -> tuple[str, int]:
    """COM2 before COM10, ttyUSB2 before ttyUSB10."""
    digits = len(device) - len(device.rstrip("0123456789"))
    if digits == 0:
        return device, -1
    return device[:-digits], int(device[-digits:])


def open_error(port: str, **line: Any) -> str:
    """Why ``port`` cannot be opened, in words a user can act on.

    ``line`` holds pyserial's line settings (baudrate, bytesize, parity, stopbits):
    a port can exist and still refuse them. Opens and closes the port at once, so
    call it only after a connection attempt failed (the port is not ours at that
    point). Blocking.
    """
    try:
        serial.Serial(port, **line).close()
    except ValueError as exc:
        return f"cannot open serial port {port}: {exc}"
    # SerialException, OSError, and termios.error when the settings are refused.
    except Exception as exc:
        return describe_open_error(port, exc)
    return f"serial port {port} opens, but the connection failed"


# pyserial on Windows: "could not open port 'COM3': PermissionError(13, 'Access is
# denied.', None, 5)". The text is localized; the last number is the Windows error.
_WINDOWS_ERROR = re.compile(r"\w+Error\((\d+), ['\"](.*)['\"], None, (\d+)\)")
WIN_FILE_NOT_FOUND = 2
WIN_ACCESS_DENIED = 5
WIN_DEVICE_NOT_CONNECTED = 1167


def describe_open_error(port: str, exc: Exception) -> str:
    """Turn a pyserial open error into a message with a hint."""
    text = str(exc)
    code = exc.errno if isinstance(exc, OSError) else None
    # pyserial puts the errno in args[0] on POSIX and only the text on Windows.
    if code is None and exc.args and isinstance(exc.args[0], int):
        code = exc.args[0]
    reason = text.split(": ", 1)[1] if text.startswith("could not open port") else text
    winerror = None
    if match := _WINDOWS_ERROR.search(text):
        reason, winerror = match.group(2).rstrip("."), int(match.group(3))

    if code == errno.ENOENT or winerror == WIN_FILE_NOT_FOUND:
        return f"serial port {port} not found; check the name or that the adapter is plugged in"
    if code == errno.EBUSY or winerror == WIN_ACCESS_DENIED:
        # On Windows "access denied" means another program has the port open.
        return f"serial port {port} is in use by another program"
    if code in (errno.EACCES, errno.EPERM):
        return (
            f"permission denied on serial port {port}; add the user to the 'dialout' group "
            "(log in again afterwards), or in Docker pass it with --device"
        )
    if code == errno.EINVAL:
        return (
            f"serial port {port} does not accept these line settings; pseudo-terminals "
            "(socat, /dev/pts/N) only take parity N"
        )
    if winerror == WIN_DEVICE_NOT_CONNECTED:
        return f"serial port {port}: the device is not connected"
    return f"cannot open serial port {port}: {reason}"
