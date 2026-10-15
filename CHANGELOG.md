# Changelog

## [Unreleased]

### Added
- Workspace export and import from the UI (**Export**, **Import…**): replace the session or
  merge into it; `GET /api/workspace`, `POST /api/workspace?mode=replace|merge`. Files
  are validated before anything is touched; merging refuses ids already in use.
- CSV register maps (**CSV…** on a window, `POST /api/polls/{id}/register-map`): columns
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

[Unreleased]: https://github.com/electrolabopen/modbus-studio/commits/main
