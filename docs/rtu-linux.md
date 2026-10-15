# Modbus RTU on Linux (and testing without hardware)

This guide covers using modbus-studio as an RTU master on a serial line: USB-RS485
adapters on Linux, a Raspberry Pi or a gateway, inside Docker, and two ways to try RTU
without any hardware.

> **Status.** RTU is tested in CI over pairs of virtual serial ports (socat), and end to
> end on Windows 10 with com0com 3.0.0.0 (simulator on one port, modbus-studio in the
> browser on the other). It has not been validated with a physical USB-RS485 adapter yet (phase 6, part 3 of the
> [roadmap](ROADMAP.md)). Reports from real installations are welcome.

## Try it without hardware

Two serial ports wired to each other are enough: the simulator answers on one end and
modbus-studio polls the other.

### Linux: socat

```bash
sudo apt install socat              # Debian, Ubuntu, Raspberry Pi OS
socat -d -d pty,raw,echo=0,link=/tmp/ttySIM pty,raw,echo=0,link=/tmp/ttySTUDIO &

# the simulator as an RTU slave (devices 1 and 2) on one end, 8N1
modbus-studio-sim --tcp-port 0 --rtu-tcp-port 0 --serial /tmp/ttySIM --parity N
```

In modbus-studio: **+ Connection** → *Modbus RTU (serial port)*, port `/tmp/ttySTUDIO`,
19200 baud, 8 data bits, parity **None**, 1 stop bit. Pseudo-terminals do not appear in
the dialog's list of ports on the server, so type the path.

Linux pseudo-terminals refuse parity. With parity E or O the connection fails with
"does not accept these line settings"; use 8N1 on both ends. Real adapters accept any
setting.

`--tcp-port 0 --rtu-tcp-port 0` turns off the simulator's TCP servers so it does not
clash with one already running (for example the docker compose stack).

### Windows: com0com

[com0com](https://sourceforge.net/projects/com0com/) is a free, open-source driver that
creates pairs of connected virtual COM ports. Tested with com0com 3.0.0.0 on Windows 10
22H2. That build's driver is not signed, which Windows only accepts in some setups (it
installed here with Secure Boot off); if it will not install, use the signed release
`com0com-2.2.2.0-x64-fre-signed.zip`.

1. Install it and open *Setup for com0com* (or `setupc.exe` from an administrator
   prompt in its install folder).
2. Create a pair of ports that Windows lists as normal COM ports. In the GUI: *Add
   Pair*, rename the two ports to free COM names (here `COM10` and `COM11`), tick
   **use Ports class** and **emulate baud rate** on both, *Apply*. Or from the prompt:

   ```bat
   setupc install PortName=COM#,EmuBR=yes PortName=COM#,EmuBR=yes
   setupc list
   ```

   `COM#` takes the next free numbers; `setupc list` shows which ones. The examples
   below use COM10 and COM11.

   Check the names Windows actually gave the ports: in the connection dialog's port
   list (or Device Manager → *Ports (COM & LPT)*) each port reads "com0com - serial
   port emulator CNCA*n*" or "CNCB*n*", and CNCA*n* is wired to CNCB*n*. Ports can end
   up with other numbers than the ones you asked for, and every *Add Pair* creates a
   new pair, so pick both ends of the same *n*.
3. Start the simulator on one end (from `backend` with the virtual environment active):

   ```bat
   modbus-studio-sim --tcp-port 0 --rtu-tcp-port 0 --serial COM10
   ```

4. Start `modbus-studio` **natively, not in Docker**: Docker Desktop cannot pass COM
   ports to a container. In the UI, **+ Connection** → *Modbus RTU (serial port)*: COM11
   appears in the port list; keep 19200 8E1 (the simulator's default) and create it.
   Open a window on device 1, FC03, address 0, quantity 28, and import
   [`examples/simulator-map.csv`](examples/simulator-map.csv).

The **Traffic** panel shows the RTU frames with their CRC. Unlike ptys, com0com accepts
parity, so 8E1, 8O1 and 8N2 all work as long as both ends agree.

The RTU tests in the backend use the same pair when you point them at it:

```powershell
$env:MODBUS_STUDIO_TEST_SERIAL_PAIR = "COM10,COM11"
pytest tests/integration/test_rtu_serial.py
```

## Finding the adapter

```bash
ls -l /dev/serial/by-id/
# usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0 -> ../../ttyUSB0
dmesg | tail          # right after plugging it in
```

Most USB-RS485 adapters show up as `/dev/ttyUSB0` (FTDI, CH340, CP210x) or
`/dev/ttyACM0`. The number depends on the order they were plugged in, so prefer the
`/dev/serial/by-id/…` link: it is named after the adapter's vendor, model and serial
number and survives reboots and replugging. The port list in the connection dialog
fills it in when you click a port.

Cheap CH340 adapters without a serial number get the same by-id name; with two of them,
use `/dev/serial/by-path/…` (the USB socket) or a udev rule.

## Permissions: the dialout group

Serial devices belong to the `dialout` group (`uucp` on Arch). Without it the
connection says "permission denied on serial port …".

```bash
sudo usermod -aG dialout "$USER"
# log out and back in (or reboot), then check:
id -nG | grep -w dialout
```

Do not run modbus-studio as root to get around this.

## udev rules

A rule gives an adapter a fixed name of your choice and sets its permissions. Find its
attributes:

```bash
udevadm info -a -n /dev/ttyUSB0 | grep -E 'idVendor|idProduct|serial' | head -3
```

`/etc/udev/rules.d/99-modbus.rules`:

```udev
# FTDI adapter on the boiler RS-485 line -> /dev/rs485-boiler
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A50285BI", SYMLINK+="rs485-boiler", GROUP="dialout", MODE="0660"

# FTDI chips buffer received bytes for 16 ms by default; 1 ms gives faster replies.
SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"
```

```bash
sudo udevadm control --reload && sudo udevadm trigger
ls -l /dev/rs485-boiler
```

The connection dialog does not list custom names like `/dev/rs485-boiler`; type it in
the port field.

### Common surprises

- **The CH340 adapter disappears a second after plugging it in** (Ubuntu 22.04 and
  later): `brltty`, a braille display driver, claims it. `sudo apt remove brltty`.
- **"in use by another program" right after plugging in**: ModemManager probes new
  `ttyACM` devices for a few seconds. Wait, or exclude the device with
  `ENV{ID_MM_DEVICE_IGNORE}="1"` in a udev rule.
- **"in use by another program"**: another master, `screen` or `minicom` still has the
  port. `sudo fuser -v /dev/ttyUSB0` shows which.

## Docker: --device

The container only sees the serial devices you pass to it. Map the stable by-id path to
a `/dev/ttyUSB*` name inside the container, so that the port list shows it:

```bash
docker run -d --name modbus-studio -p 127.0.0.1:8000:8000 -v modbus-studio-data:/data \
  --device /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0:/dev/ttyUSB0 \
  ghcr.io/electrolabopen/modbus-studio:latest
```

or in `docker-compose.yml`:

```yaml
services:
  modbus-studio:
    devices:
      - /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0:/dev/ttyUSB0
```

In the UI use `/dev/ttyUSB0`, the name inside the container.

- The app runs as a non-root user in the `dialout` group (GID 20, as on Debian, Ubuntu
  and Raspberry Pi OS). If the host gives the device another group (`ls -ln
  /dev/ttyUSB0`, fourth column), add it: `--group-add 18`, or `group_add: ["18"]` in
  compose.
- Docker resolves the device when the container starts. After unplugging the adapter,
  restart the container.
- Inside a container the adapter's description, vendor and serial number may be blank
  in the port list.
- Docker Desktop on Windows and macOS cannot pass serial ports to containers: run
  modbus-studio natively there.

## RS-485 wiring checklist

When a connection opens but every request times out, the problem is usually the line,
not the software. The **Traffic** panel shows whether anything comes back.

- **A/B polarity.** Manufacturers disagree on which is A and which is B (or D+/D−).
  If nothing answers, swap the two data wires; it does no harm.
- **Common reference.** Connect the adapter's GND to the devices' signal ground
  (often marked GND, C or 0V) when one exists.
- **Termination.** On long or fast lines, a 120 Ω resistor at each end of the bus, and
  only at the ends.
- **Biasing.** Exactly one point of the bus (often the master's adapter, a jumper or a
  DIP switch) should hold the idle line in a defined state.
- **Line settings.** Baud rate, data bits, parity and stop bits must match the devices.
  The Modbus specification's default is 19200 8E1; without parity it requires two stop
  bits (8N2), although many devices use 8N1.
- **Device ID.** Each device on the bus needs its own ID (1–247), set on the device.
- **Echo.** Some 2-wire adapters echo what they send; their own frame then appears as
  received. modbus-studio does not filter local echo yet; set the adapter to not echo
  if it can.

## What the errors mean

Connection errors appear in the sidebar under the connection; request errors in the
window.

| Message | Cause |
|---|---|
| serial port … not found | Wrong name, adapter unplugged, or (Docker) not passed with `--device` |
| permission denied on serial port … | User not in `dialout`, or the group ID differs inside the container |
| serial port … is in use by another program | Another master, terminal program or ModemManager has it open |
| … does not accept these line settings | A pseudo-terminal (socat) with parity E/O, or an unsupported baud rate |
| serial port …: the device is not connected | Windows: the USB adapter or Bluetooth device went away |
| no response (timeout) on every request | Wiring, line settings or device ID; see the checklist above |
