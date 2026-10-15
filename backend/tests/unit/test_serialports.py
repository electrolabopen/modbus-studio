import errno
import os
from types import SimpleNamespace

import pytest
import serial

from modbus_studio.core import serialports
from modbus_studio.core.serialports import describe_open_error, list_serial_ports


def comport(device, description="n/a", **extra):
    info = {"manufacturer": None, "serial_number": None, "vid": None, "pid": None, **extra}
    return SimpleNamespace(device=device, description=description, **info)


def test_lists_ports_in_natural_order_with_their_stable_path(monkeypatch, tmp_path):
    ports = [
        comport("/dev/ttyUSB10"),
        comport("/dev/ttyUSB2", "FT232R USB UART", manufacturer="FTDI", vid=0x0403, pid=0x6001),
        comport("/dev/ttyS0"),
    ]
    monkeypatch.setattr(serialports.list_ports, "comports", lambda: ports)
    # /dev/serial/by-id holds symlinks; a fake realpath keeps the test portable.
    link = tmp_path / "usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0"
    link.touch()
    real = {str(link): "/dev/ttyUSB2"}
    monkeypatch.setattr(serialports.os.path, "realpath", lambda p: real.get(str(p), str(p)))

    listed = list_serial_ports(by_id=tmp_path)
    assert [p.device for p in listed] == ["/dev/ttyS0", "/dev/ttyUSB2", "/dev/ttyUSB10"]
    usb = listed[1]
    assert usb.description == "FT232R USB UART" and usb.vid == 0x0403
    assert usb.stable_path == str(link)
    # "n/a" is pyserial's way of saying there is no description.
    assert listed[0].description == "" and listed[0].stable_path is None


def test_missing_by_id_directory_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(serialports.list_ports, "comports", lambda: [comport("COM3")])
    [port] = list_serial_ports(by_id=tmp_path / "missing")
    assert port.device == "COM3" and port.stable_path is None


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        # POSIX: pyserial passes the errno.
        (
            serial.SerialException(errno.ENOENT, "could not open port /dev/ttyUSB9: [Errno 2]"),
            "serial port P not found; check the name or that the adapter is plugged in",
        ),
        (
            serial.SerialException(errno.EBUSY, "could not open port P: [Errno 16] busy"),
            "serial port P is in use by another program",
        ),
        (
            serial.SerialException(errno.EACCES, "could not open port P: [Errno 13]"),
            "permission denied on serial port P; add the user to the 'dialout' group "
            "(log in again afterwards), or in Docker pass it with --device",
        ),
        # termios.error from tcsetattr: a Linux pty refusing parity.
        (
            Exception(errno.EINVAL, "Invalid argument"),
            "serial port P does not accept these line settings; pseudo-terminals "
            "(socat, /dev/pts/N) only take parity N",
        ),
        # Windows: only text, localized, with the Windows error code last.
        (
            serial.SerialException(
                "could not open port 'COM9': FileNotFoundError(2, 'El sistema no puede "
                "encontrar el archivo especificado.', None, 2)"
            ),
            "serial port P not found; check the name or that the adapter is plugged in",
        ),
        (
            serial.SerialException(
                "could not open port 'COM3': PermissionError(13, 'Acceso denegado.', None, 5)"
            ),
            "serial port P is in use by another program",
        ),
        (
            serial.SerialException(
                "could not open port 'COM12': OSError(22, 'El dispositivo no está "
                "conectado.', None, 1167)"
            ),
            "serial port P: the device is not connected",
        ),
        (
            serial.SerialException(
                "could not open port 'COM12': OSError(22, 'Se agotó el tiempo de espera "
                "del semáforo.', None, 121)"
            ),
            "cannot open serial port P: Se agotó el tiempo de espera del semáforo",
        ),
    ],
)
def test_open_errors_say_what_to_do(exc, expected):
    assert describe_open_error("P", exc) == expected


def test_open_error_names_a_port_that_does_not_exist():
    missing = "COM250" if os.name == "nt" else "/dev/ttyMODBUS-STUDIO-TEST"
    assert serialports.open_error(missing).startswith(f"serial port {missing} not found")
