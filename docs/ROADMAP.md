# Roadmap

v1 is single-user. It should run both on a workstation and on a gateway or Raspberry Pi
on the plant network that people open from a browser. The server binds to `127.0.0.1` by
default and has an optional bearer token.

| Phase | Scope | Done when | Status |
|---|---|---|---|
| **0. Skeleton** | Monorepo, MIT license, CI (ruff, mypy, pytest, oxlint, vitest, multi-arch Docker build), docker-compose with the simulator, empty FastAPI and React apps | `docker compose up` starts both and the simulator answers | ✅ |
| **1. Modbus core** | `ConnectionManager` (TCP, RTU over TCP, RTU), `PollTask` for FC01–04 with one lock per connection, `codec` with every data type and byte order plus **scale and unit per register**, TX/RX capture | Integration tests read from the simulator; codec tested against hand-written reference vectors | ✅ |
| **2. API + WebSocket** | REST CRUD for connections and windows; write endpoints; a WebSocket carrying values, status and traffic; error counters | Complete OpenAPI; a test client receives live values | ✅ |
| **3. Basic UI** | Dark theme, several polling windows, connection dialog, table with a format per cell or range | Three windows at different scan rates against the simulator | 🟡 minimal version: TCP / RTU-over-TCP connections, windows, live table, Tx/Err, format per window |
| **4. Writes, aliases, workspaces, register maps** | Double-click → FC05/06/15/16, aliases, JSON workspaces, **CSV register map import** (address, alias, data type, byte order, scale, unit), writes in engineering units | Write from the UI and see it on the next poll; import a CSV and get the same table as configuring it by hand | ✅ |
| **5. Traffic monitor + chart** | TX/RX hex panel with filter, pause and export; uPlot chart of selected registers | Frames visible live; the simulator sine wave plotted | ✅ |
| **6. RTU on real hardware** | Serial port discovery, `docs/rtu-linux.md` (dialout, udev, `/dev/serial/by-id`, RS-485 adapters, Docker `--device`) | Tested with socat ptys in CI and with a real USB-RS485 adapter | 🟡 part 1 ✅ port discovery, RTU in the UI, open errors. Part 2 ✅ simulator on a serial port, socat pty tests in CI, `docs/rtu-linux.md` with a com0com section, end-to-end test on Windows with com0com 3.0.0.0 (UI, traffic, window edits mid-request). Part 3 ⏳ pending: a real USB-RS485 adapter — **detecting a physical adapter has not been validated yet** (only tested without hardware) |
| **7. Integrations** | InfluxDB and MQTT exporters with configurable mapping, optional compose profiles for InfluxDB and Mosquitto | Data in InfluxDB/Grafana and in `mosquitto_sub` | ✅ part 1: InfluxDB 2.x exporter, compose profile with InfluxDB + Grafana and a simulator dashboard, `docs/influxdb.md`. Part 2: MQTT exporter: topic template, JSON payload, QoS, retain, TLS; compose profile with Mosquitto, CI check with `mosquitto_sub`, `docs/mqtt.md`. Part 3: Exporters dialog in the UI with live status, counters and a connection test; secrets typed, never shown |
| **8. Release 0.1** | README with screenshots and a GIF, docs, PyPI package, **multi-arch image `linux/amd64` + `linux/arm64` on GHCR (`ghcr.io/electrolabopen/modbus-studio`)** | `pip install modbus-studio` works on Linux, Windows and macOS; `docker run` works on x86 and on a Raspberry Pi 4/5 (64-bit OS) | 🟡 part 1: `README.es.md`, a GIF of the app in use, docs reviewed, toolbar menu on phones. Part 2: multi-arch image on GHCR, `edge` from `main`, each architecture built and started natively in CI. Part 3: PyPI package with the UI, install tested on Linux/Windows/macOS, `release.yml` (trusted publishing, versioned image tags, GitHub release) |

## CSV register map format (phase 4)

```csv
address,alias,type,byte_order,scale,unit
0,counter,uint16,ABCD,1,
2,temperature,int16,ABCD,0.1,°C
10,flow,float32,CDAB,1,m3/h
```

- `address` is the 0-based protocol address. A `4xxxx`-style notation may be accepted
  later as an import option.
- `type` is one of `int16 uint16 hex16 bin16 int32 uint32 float32 int64 uint64 float64`.
- Empty `byte_order`, `scale` and `unit` fall back to `ABCD`, `1` and no unit.
- Rows are validated (overlapping multi-register values, unknown types). Problems are
  reported per line and nothing is applied until all rows are valid.

## Open design notes

- Writes in engineering units divide by the scale and round to the nearest raw integer
  (`codec.from_engineering`). The UI must show the raw value that will actually be
  written.
- The chart history lives in the browser (up to an hour per series) and starts when a
  value is plotted; a reload starts it empty. Long-term history is the InfluxDB
  exporter's job (phase 7, `docs/influxdb.md`).
- `stop_all()` can cancel a request that is in flight. Its reply still arrives, and RTU
  frames carry no transaction ID, so the next request on the connection first waits for
  it (at most the connection timeout) and pymodbus drops it. Tested over socat ptys and
  TCP; still to check with a real adapter and slow devices in part 3.
- A reply that arrives after its request timed out can still be taken by the next
  request on an RTU line. Waiting after every timeout would halve the poll rate against
  a device that is down, so it is not done; a longer timeout avoids it.
