# Publishing over MQTT

modbus-studio can publish every polled value to an MQTT broker, one JSON message per
value, for SCADA, Node-RED, Home Assistant or any other subscriber. The exporter runs
inside the server, next to the polling windows.

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

One message per value and poll.

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
