# Changelog

## [Unreleased]

### Fixed
- The image's `org.opencontainers.image.version` label is the version without the
  "v" of the git tag (`0.2.0`, not `v0.2.0`); images from `main` say `edge`.

## [0.1.0] - 2026-10-15

First release. A Modbus master in the browser for Modbus TCP, RTU over TCP and RTU on a
serial port: polling windows with every data type and byte order, engineering values,
writes with confirmation and a write log, a traffic monitor, a real-time chart, CSV
register maps, JSON workspaces, export to InfluxDB and publishing over MQTT. Install it
with `pip install modbus-studio` or run `ghcr.io/electrolabopen/modbus-studio:0.1.0`
(amd64 and arm64).

### Added
- Python package for PyPI: the sdist and the wheel include the compiled UI and the
  license; `modbus-studio --version` and `--help`. CI installs the wheel on Linux,
  Windows and macOS (Python 3.10 and 3.13) and checks it serves the UI and polls the
  simulator.
- `release.yml`: a `v*` tag checks the version and the CHANGELOG, builds and tests the
  package, publishes it to PyPI with trusted publishing after approval, tags the image
  `X.Y.Z`, `X.Y` and `latest`, and creates the GitHub release. See `docs/releasing.md`.
- Multi-arch image (`linux/amd64`, `linux/arm64`) on `ghcr.io/electrolabopen/modbus-studio`:
  every push to `main` that passes CI is published as `edge` and `sha-<commit>`. CI also
  builds each architecture natively (an arm64 runner for linux/arm64), starts it and
  checks it serves the UI.
- `README.es.md`, a Spanish README, and a GIF of the app in use at the top of both READMEs.
- A documentation index in the README.
- Exporter settings in the UI: an **Exporters** dialog with an InfluxDB and an MQTT tab,
  the live status (state, last error, points or messages sent, errors, dropped,
  pending) and **Test connection**, which tries the settings in the form without saving
  them. Tokens and passwords are typed in password fields that start empty and are
  never filled from the server; they can be kept, replaced or removed. Dots on the
  toolbar button show each enabled exporter's state.
- API: `GET /api/exporters` (both at once), `POST /api/exporters/influxdb/test` (an empty
  write: checks URL, token, org and bucket, stores nothing) and
  `POST /api/exporters/mqtt/test` (connects once with its own client ID).
- MQTT exporter: every polled value is published as UTF-8 JSON (value in engineering
  units, unit, ISO 8601 timestamp, alias, address, device, connection, window) on a
  topic built from a template (default `modbus-studio/{connection}/{device}/{alias}`),
  with QoS 0/1/2, retain, user name and password, and TLS (CA, client certificate,
  optional verification). Configured with `GET`/`PUT /api/exporters/mqtt` and saved with
  the workspace; the password is never returned and **Export workspace** leaves it out.
  Status with connection state, last error, messages sent, errors, dropped and pending.
  The broker being down never delays polling: messages wait in a bounded buffer and are
  published, oldest first, when it is back. See `docs/mqtt.md`.
- docker compose profile `mqtt`: Mosquitto 2 with a password (`MQTT_USERNAME`,
  `MQTT_PASSWORD`), port on 127.0.0.1 only, and the exporter set up. CI reads the
  values back with `mosquitto_sub`.
- InfluxDB 2.x exporter: every polled value is written as a point (measurement = window,
  tags connection, device, alias, address and unit, field `value` in engineering units),
  in batches through the HTTP API. Configured with `GET`/`PUT /api/exporters/influxdb`
  and saved with the workspace; the token is never returned and **Export workspace**
  leaves it out. Status with state, last error, points sent, writes, errors, dropped and
  pending points. InfluxDB being down or slow never delays polling: points wait in a
  bounded buffer and are written when it is back. See `docs/influxdb.md`.
- docker compose profile `influxdb`: InfluxDB 2.7 and Grafana 11 with the exporter set
  up and a dashboard for the simulator. CI checks the values arrive in InfluxDB. Ports
  published on 127.0.0.1 only; `GRAFANA_PASSWORD` and `GRAFANA_ANONYMOUS` set Grafana's
  admin password and anonymous read-only access.
- README: screenshots (polling window with chart, traffic monitor, Grafana) and a
  Features section split into what works now and what is in development.
- The compose demo window now covers the whole simulator map (addresses 0–27) with its
  aliases, data types and units.
- The simulator serves RTU on a serial port: `modbus-studio-sim --serial PORT` with
  `--baudrate`, `--bytesize`, `--parity` (default E) and `--stopbits`; `--tcp-port 0` /
  `--rtu-tcp-port 0` turn off the TCP servers. A port that does not open is reported
  with its reason.
- [`docs/rtu-linux.md`](docs/rtu-linux.md): USB-RS485 adapters on Linux (`dialout`, udev
  rules, `/dev/serial/by-id`, FTDI latency, brltty and ModemManager), Docker `--device`,
  an RS-485 wiring checklist, and trying RTU without hardware with socat (Linux) or
  com0com (Windows).
- RTU tests over a real serial line: CI runs the simulator and modbus-studio on a socat
  pty pair; `MODBUS_STUDIO_TEST_SERIAL_PAIR=COM10,COM11` runs them on a com0com pair.
- A serial port that refuses the line settings (e.g. parity on a Linux pseudo-terminal)
  says so.
- Modbus RTU connections from the UI: **+ Connection** → "Modbus RTU (serial port)" with
  baud rate, data bits, parity and stop bits (default 19200 8E1). The dialog lists the
  serial ports of the machine running the server (`GET /api/serial-ports`) with
  description, manufacturer, VID:PID and serial number; a click fills the port, using the
  `/dev/serial/by-id/…` name on Linux so it survives replugging. Ports already used by a
  connection are marked. The sidebar shows the line settings, e.g. `COM3 · 19200 8E1`.
- A serial port that does not open says why: not found, in use by another program,
  permission denied (with the `dialout` / `--device` hint) or device not connected,
  including on non-English Windows.
- Importing a CSV register map into a window that is too small offers **Grow window and
  apply**, which widens the window to the smallest range that holds every row and applies
  the map in one step (`POST /api/polls/{id}/register-map?fit=true`; a failed import
  returns the suggested `fit`). Offered only when that alone fixes the file and Modbus
  can read the result in one request.
- The Chart panel points out rows selected in the windows that are not plotted yet, with
  a button to plot them.
- Clearer button names: **Export workspace**, **Import workspace…** (top bar) and
  **Import CSV map…** (each window).
- Real-time chart (**Chart** in the toolbar, uPlot): select rows in a window and press
  **Plot** (or **Unplot**); a 32/64-bit value is one series, coils and discrete inputs
  are drawn as steps, failed reads leave a gap. Up to 8 series, marked with their color
  in the windows. Legend with the latest value (or the value under the cursor) and unit;
  click a series to hide it, ✕ to remove it. Time span 30 s to 1 h; pause, drag to
  zoom (pauses), double-click to reset; CSV export of what is shown; clear. Samples are
  kept in the browser for up to an hour per series and start recording when a value is
  plotted; the plotted values are remembered per browser.
- Traffic monitor (**Traffic** in the toolbar): live TX/RX frames with time, connection,
  device, function, response time and a description of exception responses and
  malformed frames (bad RTU CRC, wrong MBAP length, short frames). Filters by
  connection, direction, device, function, hex bytes and "errors only"; pause keeps the
  view and counts new frames; TX/RX/exception/malformed counters; CSV export of the
  filtered frames; clear. Frames are only streamed while the monitor is open.
- Workspace export and import from the UI (**Export workspace**, **Import workspace…**): replace the session or
  merge into it; `GET /api/workspace`, `POST /api/workspace?mode=replace|merge`. Files
  are validated before anything is touched; merging refuses ids already in use.
- CSV register maps (**Import CSV map…** on a window, `POST /api/polls/{id}/register-map`): columns
  address, alias, type, byte_order, scale, unit; `,` or `;` separated (with decimal
  comma), BOM and `#` comments accepted. All rows are validated first (unknown types,
  overlapping values, rows outside the window, 4xxxx-style addresses, rows hidden by the
  window format) and reported per line. Example for the simulator in
  `docs/examples/simulator-map.csv`.
- Write log: every write (time, connection, device, function, address, value before and
  after, raw data, result) is kept in `/data/writes.jsonl`, listed by `GET /api/writes`,
  pushed over the WebSocket and shown in the **Write log** panel. Rejected writes are
  logged too.
- The write dialog opens with Cancel focused, so a stray Enter does not write.
- Per-cell and per-range display formats from the table: select rows (click,
  Shift+click for a range) and use **Format…**, or double-click an address. Sets data
  type, byte order, scale and unit; a range of 32/64-bit values steps two or four
  registers at a time, and "Reset to window format" clears it. Backed by
  `PATCH /api/polls/{id}/formats`, which keeps omitted fields per cell, refuses to start
  in the middle of a value or run past the window, and drops entries equal to the
  window default.
- Aliases are edited in place: double-click the alias cell, Enter saves, Esc cancels.
- Write by double-clicking a cell (coils and holding registers). A confirmation dialog
  shows the function (05/06/15/16), address range, data type, byte order and scale, the
  value the device will hold and the raw coils/registers sent; it warns when the value
  cannot be stored exactly. Accepts decimal, `0x…` and `0b…` input.
  `POST /api/polls/{id}/write/preview` returns the same plan without writing, and
  `POST /api/polls/{id}/write` now returns it (200 instead of 204).
- Read-only connections (`read_only`): every write is rejected with 403. Toggle it from
  the sidebar (RW/RO) or when creating the connection; changing it, or the name, does
  not restart polling.
- The workspace (connections, windows, per-register formats) is saved after every change
  and restored at startup (`MODBUS_STUDIO_STATE_FILE`). Writes are atomic and coalesced;
  an unreadable file is moved aside instead of blocking startup. In Docker it lives in
  the `modbus-studio-data` volume; CI kills the app container and checks it comes back.
- docker compose preloads a connection to the simulator and a demo window
  (`docker/demo-workspace.json`, loaded through `MODBUS_STUDIO_WORKSPACE`).
- CI smoke test (`docker/smoke_test.py`) checking app → simulator inside the compose
  network over TCP, RTU over TCP and the `modbus-studio-sim` alias.
- Connections report why they are down (`last_error`): unknown host, refused or timed
  out, with a hint when `127.0.0.1` is used inside a container. Shown in the sidebar.

### Fixed
- The top bar no longer overflows on narrow screens: below 720 px the toolbar buttons
  move into a **☰ Menu** drop-down (closed by picking an item, Escape or a tap outside),
  and between 720 and 1200 px they wrap onto a second row. Polling windows fit phones
  narrower than 340 px.
- CONTRIBUTING: the development setup ran `cd frontend` from `backend/`.
- The sidebar no longer splits an RTU connection's line settings (`COM21 · 19200 8E1`)
  over two lines: the RW and ✕ buttons moved next to the name.
- RTU and RTU over TCP: after a request was cancelled in flight (stopping or editing a
  window), its late reply could be taken as the reply to the next request on the
  connection, showing another address's values. The next request now waits for that
  reply to arrive and drops it, for at most the connection timeout.
- Stopping a polling window (and so shutting down the app) could hang forever on
  Python < 3.12: `asyncio.wait_for`, used by pymodbus for every response, can swallow a
  cancellation. This hung the py3.10 CI job intermittently. CI jobs now have time limits.
- Log messages from modbus-studio itself (below WARNING) were never printed.
- The simulator ignored SIGTERM in Docker and was killed after 10 s.
- `docker compose up --wait` failed because the simulator had no healthcheck.
- Stopping several windows on a shared connection could let one more request out.
- Unresolvable hosts filled the log with "Future exception was never retrieved".

- REST API for connections, polling windows, writes (raw FC05/06/15/16 and per-cell writes in
  engineering units) and traffic; Modbus errors are returned as 502 with the exception code.
- WebSocket `/api/ws` pushing snapshots, decoded poll results, connection state and (opt-in)
  raw traffic; the token goes in the first message, never in the URL.
- Minimal UI: create TCP / RTU-over-TCP connections, open polling windows, live table with
  Tx/Err counters, display format and byte order per window, reset, edit and close.
- Project skeleton: FastAPI backend, React + Vite + TypeScript frontend, docker-compose with a
  slave simulator, CI with a multi-arch (amd64/arm64) image build.
- Modbus core: TCP, RTU over TCP and RTU connections with one request lock per connection;
  periodic polling of FC01–FC04 with per-window statistics; FC05/06/15/16 writes.
- Codec for int16/uint16/hex/binary, 32-bit and 64-bit integers, float32/float64 in byte
  orders ABCD, CDAB, BADC and DCBA, with scale and unit per register.
- Raw TX/RX frame capture for the traffic monitor.
- Optional bearer token for the API; the server binds to 127.0.0.1 by default.
- `modbus-studio-sim`: simulator with time-varying registers, served over TCP and RTU over TCP.

[Unreleased]: https://github.com/electrolabopen/modbus-studio/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/electrolabopen/modbus-studio/releases/tag/v0.1.0
