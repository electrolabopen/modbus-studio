# Exporting to InfluxDB

modbus-studio can write every polled value to an InfluxDB 2.x bucket, to keep a history
and graph it in Grafana. The exporter runs inside the server, next to the polling
windows.

## Try it with docker compose

The `influxdb` profile adds InfluxDB 2.7 and Grafana 11, points the exporter at that
InfluxDB and loads a dashboard for the bundled simulator:

```bash
docker compose --profile influxdb up --build
```

| | URL | Login |
|---|---|---|
| modbus-studio | <http://127.0.0.1:8000> | |
| Grafana | <http://127.0.0.1:3000> | dashboards open read-only without login; `admin` / `modbus-studio` to edit |
| InfluxDB | <http://127.0.0.1:8086> | `admin` / `modbus-studio`, org `modbus-studio`, bucket `modbus` |

The Grafana home page is the *modbus-studio: simulator* dashboard: the sine wave in its
five encodings (the lines must overlap), the int32 and uint32 constants, the temperature
in °C and the sawtooth, plus a panel for any value of any window.

The demo window has the simulator's register map applied, so its values carry aliases
such as `temperature` or `sine ABCD`. The demo workspace only seeds the first start: if
your `modbus-studio-data` volume predates it, import
[`examples/simulator-map.csv`](examples/simulator-map.csv) into a window at address 0,
quantity 28, and name the window *Simulator*, or pick your window in the dashboard's
*Window* list.

The token and passwords in `docker-compose.yml` are **development defaults**; see
[Ports and credentials](#ports-and-credentials) before using the profile anywhere others
can reach.

The `influxdb-setup` container configures the exporter once and exits. It leaves alone
an exporter that is already configured, so later changes are kept.

### Ports and credentials

InfluxDB and Grafana publish their ports on **127.0.0.1 only**
(`127.0.0.1:8086:8086` and `127.0.0.1:3000:3000` in `docker-compose.yml`), like
modbus-studio and the simulator: they cannot be reached from other machines. To open
one of them to the network, change its `ports:` binding, and set the credentials below
first.

The defaults come from these variables, read from the environment or from a `.env` file
next to `docker-compose.yml`:

| Variable | Default | Used for |
|---|---|---|
| `INFLUXDB_TOKEN` | `modbus-studio-dev-token` | InfluxDB's admin token, also used by the exporter and by Grafana's data source |
| `INFLUXDB_PASSWORD` | `modbus-studio` | InfluxDB's `admin` user |
| `GRAFANA_PASSWORD` | `modbus-studio` | Grafana's `admin` user |
| `GRAFANA_ANONYMOUS` | `true` | dashboards readable without logging in (Viewer role) |

```bash
# .env
INFLUXDB_TOKEN=<a long random string>
INFLUXDB_PASSWORD=<…>
GRAFANA_PASSWORD=<…>
GRAFANA_ANONYMOUS=false
```

The tokens and passwords are applied **only when the volumes are created**, at the
first start. After that:

- **Grafana's admin password**: change it in Grafana (*Profile → Change password*,
  logged in as `admin`), or from the command line:

  ```bash
  docker compose --profile influxdb exec grafana grafana cli admin reset-admin-password '<new password>'
  ```

  Changing `GRAFANA_PASSWORD` later has no effect on an existing `grafana-data` volume.
- **Grafana's anonymous access**: set `GRAFANA_ANONYMOUS=false` and recreate the
  container (`docker compose --profile influxdb up -d grafana`). Grafana then asks for a
  login on every page; dashboards stay as they are. This one takes effect at any time,
  since it is read at every start.
- **InfluxDB's password and token**: change them in InfluxDB's UI
  (<http://127.0.0.1:8086>) or with the `influx` CLI in the container. If you replace
  the token, update the exporter (`PUT /api/exporters/influxdb` with the new `token`)
  and Grafana's data source, which reads `INFLUXDB_TOKEN`: set the variable to the new
  token and recreate the `grafana` container. Alternatively, start over with
  `docker compose --profile influxdb down -v`, which deletes the stored data **and
  modbus-studio's workspace**.

## What is written

One point per value and poll:

```text
Simulator,address=2,alias=temperature,connection=Simulator\ (compose),device=1,unit=°C value=21.5 1792097490054160600
```

| Part | Content |
|---|---|
| measurement | the window's name (its id when it has none) |
| tag `connection` | the connection's name (its id when it has none) |
| tag `device` | the slave ID |
| tag `alias` | the register's alias, or its address when it has none |
| tag `address` | the 0-based protocol address |
| tag `unit` | the unit, when set |
| field `value` | the engineering value: after data type, byte order and scale. Always a float, so changing a register's scale does not change the field type; coils and discrete inputs are booleans |
| time | when the poll finished, in nanoseconds |

A 32- or 64-bit value is one point, at the address of its first register. Failed polls
and values that cannot be decoded write nothing, so they show as gaps.

Renaming a window, a connection or an alias starts new series: InfluxDB identifies a
series by its measurement and tags.

### Querying it

```flux
from(bucket: "modbus")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "Simulator" and r.alias == "temperature")
  |> aggregateWindow(every: 10s, fn: mean)
```

## Configuring it

Click **Exporters** in the toolbar and pick the *InfluxDB* tab. The dialog shows the
status live (state, last error, counters) and has a **Test connection** button that
tries the settings as they are in the form, without saving them. **Save** applies them
at once. The token is typed but never shown: the field starts empty with "saved
(hidden)" when one is set; leave it empty to keep it, or tick *Remove the saved
token*. The dots on the **Exporters** button show each enabled exporter's state
(green: working, amber: starting, red: failing).

![Exporters dialog](screenshots/exporters.jpg)

The same settings through the API:

```bash
curl -X PUT http://127.0.0.1:8000/api/exporters/influxdb \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true, "url": "http://influxdb.local:8086", "org": "plant",
       "bucket": "modbus", "token": "…"}'
```

| Setting | Default | |
|---|---|---|
| `enabled` | `false` | |
| `url` | `http://localhost:8086` | `http://` or `https://` |
| `org`, `bucket` | | must exist in InfluxDB |
| `token` | | an API token with write access to the bucket |
| `aliased_only` | `false` | export only registers that have an alias |
| `flush_interval_ms` | `1000` | how often buffered points are written |
| `batch_size` | `5000` | points per write request |
| `buffer_size` | `100000` | points kept while InfluxDB is unreachable |
| `timeout_s` | `5` | per write request |
| `verify_tls` | `true` | check the server certificate on `https://` |

The token is never sent back: `GET /api/exporters/influxdb` says `token_set: true`. In a
`PUT`, leave `token` out (or `null`) to keep the current one, or send `""` to remove it.
The settings are saved with the workspace, the token included, in the server's state
file (`/data/workspace.json` in Docker). **Export workspace** leaves the token out, and
importing such a file keeps the token already set.

**Test connection** (`POST /api/exporters/influxdb/test`, same body as the `PUT`) makes
an empty write to the bucket: InfluxDB checks the URL, the token, the org and the bucket
and answers without storing anything. A missing token means the saved one.

## Status, errors and buffering

`GET /api/exporters/influxdb` also returns the status:

| Field | |
|---|---|
| `state` | `disabled`, `incomplete` (enabled but org, bucket or token missing), `idle` (nothing sent yet), `ok` (the last write worked), `error` (the last write failed) |
| `last_error`, `last_error_at` | the last failure and when it happened, e.g. "unauthorized: check the token" or "cannot connect to http://influxdb:8086" |
| `last_success_at` | the last successful write |
| `points_sent`, `writes`, `errors` | counters since the server started |
| `dropped` | points discarded: the buffer was full, or InfluxDB rejected them as malformed |
| `pending` | points waiting to be written |

**InfluxDB never slows down polling.** Polling hands the values to a buffer and goes on;
a separate task writes the buffer. While InfluxDB is down or slow the points wait, the
retries back off from 1 s to 30 s, and the points are written when InfluxDB is back.
When the buffer is full, the oldest points are dropped and counted in `dropped`.
Points that InfluxDB rejects as malformed (HTTP 400) are dropped at once, so they do not
block the ones behind them. Changing the URL, org or bucket discards the points not yet
written to the old destination.

At shutdown the server tries for up to 2 s to write what is left.
