# Publishing over MQTT

modbus-studio can publish polled values to an MQTT broker, one JSON message per value,
for SCADA, Node-RED, Home Assistant or any other subscriber: every value of every poll,
or only the values that change ([report by exception](#publishing-on-change-report-by-exception)).
The exporter runs inside the server, next to the polling windows.

## Try it with docker compose

The `mqtt` profile adds Mosquitto 2 and points the exporter at it:

```bash
docker compose --profile mqtt up --build
```

Watch the messages with `mosquitto_sub`, from inside the Mosquitto container:

```bash
docker compose exec mosquitto mosquitto_sub -u modbus-studio -P modbus-studio -t 'modbus-studio/#' -v
```

```text
modbus-studio/Simulator (compose)/1/temperature {"value":63.3,"unit":"°C","timestamp":"2026-10-16T01:21:01.276Z","alias":"temperature","address":2,"device":1,"connection":"Simulator (compose)","window":"Simulator"}
```

or from the host, with any client, at `127.0.0.1:1883` (user `modbus-studio`, password
`modbus-studio`). Both profiles can run together:
`docker compose --profile influxdb --profile mqtt up`.

The `mqtt-setup` container configures the exporter once and exits. It leaves alone an
exporter that is already configured, so later changes are kept.

### Ports and credentials

Mosquitto publishes its port on **127.0.0.1 only** (`127.0.0.1:1883:1883`), like the
rest of the stack. It does not accept anonymous clients: its only account comes from
these variables, read from the environment or from a `.env` file next to
`docker-compose.yml`:

| Variable | Default |
|---|---|
| `MQTT_USERNAME` | `modbus-studio` |
| `MQTT_PASSWORD` | `modbus-studio` |

The defaults are for development. The password file is written again at every start
of the container, so to change the password set `MQTT_PASSWORD` and recreate it
(`docker compose --profile mqtt up -d mosquitto`). The exporter then reports
"connection refused by the broker: Not authorized" until you give it the new password
too (`PUT /api/exporters/mqtt` with `password`).

The compose broker listens without TLS, which is fine inside the compose network and
on 127.0.0.1. Before opening its port to a network, give it a TLS listener (see
[Mosquitto's documentation](https://mosquitto.org/man/mosquitto-conf-5.html)) and turn on
`tls` in the exporter.

## What is published

One message per value and poll, or, with `publish_mode` `on_change`, only when the value
changes (see [below](#publishing-on-change-report-by-exception)).

**Topic**: the `topic` template, by default `modbus-studio/{connection}/{device}/{alias}`.

| Placeholder | Replaced by |
|---|---|
| `{connection}` | the connection's name (its id when it has none) |
| `{device}` | the slave ID |
| `{window}` | the window's name (its id when it has none) |
| `{alias}` | the register's alias, or its address when it has none |
| `{address}` | the 0-based protocol address |
| `{unit}` | the unit (empty when not set) |

A value never adds topic levels: `/`, `+` and `#` inside a name or alias become `_`.
The template itself cannot contain the wildcards `+` or `#`, nor start with `$`.

**Payload**: UTF-8 JSON.

| Key | |
|---|---|
| `value` | the engineering value, after data type, byte order and scale: a number, or `true`/`false` for coils and discrete inputs |
| `unit` | the unit, `""` when not set |
| `timestamp` | when the poll finished, ISO 8601 in UTC with milliseconds |
| `alias`, `address`, `device`, `connection`, `window` | where the value comes from, so a subscriber to a wildcard knows it without parsing the topic |

A 32- or 64-bit value is one message, at the address of its first register. Failed
polls and values that cannot be decoded publish nothing.

## Configuring it

Click **Exporters** in the toolbar and pick the *MQTT* tab. The dialog shows the
status live (state, last error, counters) and has a **Test connection** button that
tries the settings as they are in the form, without saving them. **Save** applies them
at once. The password is typed but never shown: the field starts empty with "saved
(hidden)" when one is set; leave it empty to keep it, or tick *Remove the saved
password*. The dots on the **Exporters** button show each enabled exporter's state
(green: working, amber: starting, red: failing).

![Exporters dialog](screenshots/exporters.jpg)

The same settings through the API:

```bash
curl -X PUT http://127.0.0.1:8000/api/exporters/mqtt \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true, "host": "broker.local", "port": 8883, "tls": true,
       "username": "modbus", "password": "…", "topic": "plant/{window}/{alias}",
       "qos": 1}'
```

| Setting | Default | |
|---|---|---|
| `enabled` | `false` | |
| `host`, `port` | `localhost`, `1883` | the broker; usually `8883` with TLS |
| `client_id` | | empty: `modbus-studio-` and a random suffix, new at every server start |
| `username`, `password` | | leave the user name empty for an anonymous broker |
| `topic` | `modbus-studio/{connection}/{device}/{alias}` | see above |
| `qos` | `0` | `0`, `1` or `2` |
| `retain` | `false` | the broker keeps the last value of each topic for new subscribers |
| `aliased_only` | `false` | publish only registers that have an alias |
| `publish_mode` | `every_poll` | `every_poll`: every value of every poll; `on_change`: report by exception, see below |
| `deadband` | `0` | `on_change`: smallest change published, in engineering units; `0`: any change |
| `heartbeat_s` | `0` | `on_change`: publish an unchanged value again after this many seconds; `0`: never |
| `keepalive_s` | `60` | |
| `buffer_size` | `10000` | messages kept while the broker is unreachable |
| `tls` | `false` | connect with TLS |
| `ca_file` | | CA certificate (PEM) that signed the broker's certificate; empty: the system's CAs |
| `cert_file`, `key_file` | | client certificate and key (PEM), for brokers that require one |
| `verify_tls` | `true` | check the broker's certificate and host name |

The TLS files are paths on the machine running modbus-studio (inside the container,
in Docker: mount them, e.g. `./certs:/certs:ro`).

The password is never sent back: `GET /api/exporters/mqtt` says `password_set: true`.
In a `PUT`, leave `password` out (or `null`) to keep the current one, or send `""` to
remove it. The settings are saved with the workspace, the password included, in the
server's state file (`/data/workspace.json` in Docker). **Export workspace** leaves the
password out, and importing such a file keeps the password already set.

Any change is applied at once: the client disconnects and connects again with the new
settings.

**Test connection** (`POST /api/exporters/mqtt/test`, same body as the `PUT`) connects to
the broker once, waits for its answer and disconnects. It uses its own client ID
(the exporter's plus `-test`), so the running exporter stays connected. A missing
password means the saved one.

## Publishing on change (report by exception)

Catching short states needs a fast scan rate: a door bit that is set for 100 ms needs
polling every 50 ms. Published every poll, that is 20 messages a second per value, nearly
all of them repeating the previous one. With `publish_mode` `on_change` (in the dialog,
**Publish: On change**) the exporter keeps the last value it published for each value of
each window and publishes a new message only when:

- **the value changed** by more than the deadband since the last message (not since the
  last poll, so a slow drift is published once it adds up). Coils, discrete inputs and
  other booleans are published whenever they flip. With the deadband at `0` any change is
  published;
- **it is the first value**: after the server starts, after the window is added, and
  after any change of the exporter's settings, every value is published once, so
  subscribers get the current state;
- **the previous read failed**: after a timeout, an exception or a lost connection (for
  the whole window), or a value that could not be decoded (for that value), the next
  valid value is published even if it equals the last message;
- **its topic or unit changed**, e.g. after renaming its alias: the new topic gets the
  value at once;
- **the heartbeat is due**: with `heartbeat_s` above 0, a value that has not changed is
  published again that many seconds after its last message, so subscribers can tell the
  device is still being read.

The heartbeat comes from the polls: it is only sent with a valid read. While a device does
not answer, nothing is published for it, heartbeat included, and a subscriber that misses
the heartbeat knows the value is stale.

The payload is the same as in `every_poll`, and its `timestamp` is when the poll that saw
the change finished: the time of a change is known to within one scan period. Each message
is then an event (what changed and when); a scan faster than the shortest state you need
to see is still needed, but it no longer costs a message per poll.

With the default every-poll mode, the example of the door bit gives 20 messages a second;
on change, it gives one message when the door opens and one when it closes.

### Deadband per value

The exporter's `deadband` applies to every value. A value can have its own: in the cell
format dialog (double-click the address, or **Format…**), **MQTT deadband** sets it for
that value or for the selected range; leave it empty to use the exporter's. A value's
own deadband replaces the exporter's, also when it is smaller (`0` publishes every change
of that value even if the exporter's deadband is larger).

Through the API, it is the `deadband` of the cell format:

```bash
# 0.5 for the values at addresses 10 to 17
curl -X PATCH http://127.0.0.1:8000/api/polls/<window id>/formats \
  -H 'Content-Type: application/json' -d '{"start": 10, "end": 17, "deadband": 0.5}'
# back to the exporter's deadband
curl -X PATCH http://127.0.0.1:8000/api/polls/<window id>/formats \
  -H 'Content-Type: application/json' -d '{"start": 10, "end": 17, "deadband": null}'
```

and in a CSV register map, the optional `deadband` column (empty: the exporter's):

```csv
address,alias,type,byte_order,scale,unit,deadband
2,temperature,int16,ABCD,0.1,°C,0.5
10,flow,float32,CDAB,1,m3/h,
```

Coils and discrete inputs take no deadband: they are published when they flip. The
deadbands are saved with the windows in the workspace.

### Example

```bash
curl -X PUT http://127.0.0.1:8000/api/exporters/mqtt \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true, "host": "mosquitto", "username": "modbus-studio",
       "publish_mode": "on_change", "deadband": 0.5, "heartbeat_s": 60}'
```

With the simulator, the counter is published every second (it changes every second),
the temperature only when it moves by more than 0.5 °C, and the constants once a
minute, from the heartbeat.

With `retain`, the broker keeps the last message of each topic, so a subscriber that
connects between two changes still gets the current value at once.

## Status, errors and buffering

`GET /api/exporters/mqtt` also returns the status:

| Field | |
|---|---|
| `connected` | whether the client is connected to the broker |
| `state` | `disabled`, `idle` (connecting for the first time), `ok` (connected), `error` (not connected: see `last_error`) |
| `last_error`, `last_error_at` | the last failure and when it happened, e.g. "connection refused by the broker: Not authorized", "TLS: certificate of broker:8883 not accepted: …" or "broker:8883 closed the connection before accepting it: check the port and the TLS setting". It stays visible after the client reconnects |
| `last_success_at` | the last message sent, or the last connection |
| `points_sent`, `writes` | messages sent (QoS 0: written to the network; QoS 1 and 2: acknowledged by the broker), since the server started |
| `errors` | failed connection attempts and failed publishes |
| `dropped` | messages discarded: the buffer was full, or QoS 0 messages lost with a connection |
| `pending` | messages waiting to be published |
| `unchanged` | `on_change`: values not published because they had not changed |

**The broker never slows down polling.** Polling hands the values to a buffer and goes
on; the MQTT client runs in a thread of its own and reconnects by itself, waiting 1 s,
then 2, 4… up to 30 s between attempts. While the broker is unreachable the messages
wait, and they are published, oldest first, as soon as it is back. When the buffer is
full the oldest messages are dropped and counted in `dropped`. Changing the host, the
port or the topic discards the messages not yet published.

QoS 0 messages that the client had already taken when a connection drops are lost
(and counted in `dropped`); with QoS 1 or 2 the client sends them again after
reconnecting.

At shutdown the server tries for up to 2 s to publish what is left.
