"""Smoke test for the docker compose stack: app -> simulator over the compose network.

    docker compose up -d --build
    python docker/smoke_test.py

    # persistence across a restart:
    python docker/smoke_test.py persist-write
    docker compose kill modbus-studio && docker compose up -d --wait
    python docker/smoke_test.py persist-check

    # export to InfluxDB (profile "influxdb"):
    docker compose --profile influxdb up -d --wait
    python docker/smoke_test.py influxdb

    # publish over MQTT (profile "mqtt"), read back with mosquitto_sub:
    docker compose --profile mqtt up -d --wait
    python docker/smoke_test.py mqtt

Checks, through the app's REST API on the host:
  1. the preloaded demo window (docker/demo-workspace.json) polls the simulator
     by its service name and gets valid responses;
  2. the simulator also answers under its network alias and over RTU over TCP;
  3. a connection to 127.0.0.1 from inside the container fails with an
     explanation instead of a bare "not connected";
  4. (persist-*) connections and windows survive a restart of the app container;
  5. (influxdb) the exporter set up by the profile writes the demo window's values,
     with their tags, into InfluxDB;
  6. (mqtt) the exporter set up by the profile publishes the demo window's values to
     Mosquitto, as read by mosquitto_sub inside the mosquitto container.

Standard library only, so it runs on any CI runner or workstation with Python 3.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

BASE = os.environ.get("MODBUS_STUDIO_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("MODBUS_STUDIO_TOKEN") or None
TIMEOUT_S = float(os.environ.get("SMOKE_TIMEOUT_S", "60"))
INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://127.0.0.1:8086").rstrip("/")
INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "modbus-studio-dev-token")
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "modbus-studio")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "modbus-studio")


def api(method: str, path: str, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=5) as res:
        raw = res.read()
    return json.loads(raw) if raw else None


def wait_until(what: str, check: Callable[[], Any], timeout: float = TIMEOUT_S) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = check()
            if last:
                print(f"ok   {what}")
                return last
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = exc
        time.sleep(1)
    raise AssertionError(f"timed out waiting for: {what} (last: {last!r})")


def valid_polls(poll_id: str, at_least: int = 3) -> Callable[[], bool]:
    def check() -> bool:
        data = api("GET", f"/api/polls/{poll_id}/data")
        return bool(data and data["ok"] and data["stats"]["valid"] >= at_least)

    return check


def try_connection(conn_id: str, connection: dict[str, Any]) -> None:
    """Create a connection with one window, wait for valid data, then remove both."""
    api("POST", "/api/connections", {"id": conn_id, "timeout_s": 1, **connection})
    try:
        api("POST", "/api/polls", {"id": conn_id, "connection_id": conn_id, "quantity": 5})
        where = f"{connection['type']} {connection['host']}:{connection['port']}"
        wait_until(f"valid responses from {where}", valid_polls(conn_id), timeout=20)
    finally:
        api("DELETE", f"/api/connections/{conn_id}?cascade=true")


def dump_state() -> None:
    for path in ("/api/connections", "/api/polls"):
        try:
            print(f"--- {path}\n{json.dumps(api('GET', path), indent=2)}")
        except (urllib.error.URLError, OSError, ValueError) as exc:  # diagnostics only
            print(f"--- {path}: {exc}")


def connectivity() -> None:
    # 1. Preloaded workspace: connection "simulator" + window "demo".
    conns = {c["config"]["id"]: c for c in api("GET", "/api/connections")}
    assert "simulator" in conns, f"preloaded connection missing: {sorted(conns)}"
    host = conns["simulator"]["config"]["host"]
    assert host == "simulator", f"preloaded connection should use the service name: {host!r}"
    wait_until("demo window polls the simulator", valid_polls("demo"))
    state = api("GET", "/api/connections/simulator")
    assert state["state"] == "connected", state

    # 2. Other ways of reaching the simulator from the app container.
    try_connection("smoke-alias", {"type": "tcp", "host": "modbus-studio-sim", "port": 5020})
    try_connection("smoke-rtu", {"type": "rtu_over_tcp", "host": "simulator", "port": 5021})

    # 3. Loopback inside the container is the app itself: the error must say so.
    loop = {"id": "smoke-loop", "type": "tcp", "host": "127.0.0.1", "port": 5020, "timeout_s": 1}
    api("POST", "/api/connections", loop)
    try:
        api("POST", "/api/polls", {"id": "smoke-loop", "connection_id": "smoke-loop"})
        data = wait_until(
            "127.0.0.1 inside the container is reported",
            lambda: (d := api("GET", "/api/polls/smoke-loop/data")) and not d["ok"] and d,
            timeout=20,
        )
        assert "container" in data["error"], data["error"]
    finally:
        api("DELETE", "/api/connections/smoke-loop?cascade=true")


PERSIST_ID = "smoke-persist"
PERSIST_ALIAS = "survives restarts"


def persist_write() -> None:
    """Create a connection and a window; the app must save them to its volume."""
    if any(c["config"]["id"] == PERSIST_ID for c in api("GET", "/api/connections")):
        api("DELETE", f"/api/connections/{PERSIST_ID}?cascade=true")
    conn = {"id": PERSIST_ID, "type": "tcp", "host": "simulator", "port": 5020}
    api("POST", "/api/connections", conn)
    window = {
        "id": PERSIST_ID,
        "connection_id": PERSIST_ID,
        "address": 2,
        "quantity": 1,
        "formats": {"2": {"alias": PERSIST_ALIAS, "scale": 0.1, "unit": "°C"}},
    }
    api("POST", "/api/polls", window)
    wait_until("new window polls the simulator", valid_polls(PERSIST_ID))
    # Saves are coalesced for 0.5 s. Waiting lets CI kill the container instead of
    # stopping it, which proves the change was saved right away, not at shutdown.
    time.sleep(2)


def persist_check() -> None:
    """After a restart the window from persist_write() is back and polling; then remove it."""
    conns = {c["config"]["id"] for c in api("GET", "/api/connections")}
    assert PERSIST_ID in conns, f"connection lost on restart: {sorted(conns)}"
    poll = api("GET", f"/api/polls/{PERSIST_ID}")
    alias = poll["definition"]["formats"]["2"]["alias"]
    assert alias == PERSIST_ALIAS, f"per-register format lost on restart: {alias!r}"
    print("ok   connection, window and register format restored")
    wait_until("restored window polls the simulator", valid_polls(PERSIST_ID))
    api("DELETE", f"/api/connections/{PERSIST_ID}?cascade=true")


def flux(query: str) -> list[dict[str, str]]:
    """Run a Flux query on the compose InfluxDB; rows of the CSV answer."""
    req = urllib.request.Request(
        f"{INFLUXDB_URL}/api/v2/query?org=modbus-studio", data=query.encode(), method="POST"
    )
    req.add_header("Authorization", f"Token {INFLUXDB_TOKEN}")
    req.add_header("Content-Type", "application/vnd.flux")
    req.add_header("Accept", "application/csv")
    with urllib.request.urlopen(req, timeout=10) as res:
        lines = [line for line in res.read().decode().splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].split(",")
    return [dict(zip(header, line.split(","), strict=False)) for line in lines[1:]]


def influxdb() -> None:
    wait_until(
        "the exporter writes to InfluxDB",
        lambda: (
            (s := api("GET", "/api/exporters/influxdb")["status"])["state"] == "ok"
            and s["points_sent"] > 0
        ),
    )
    rows = wait_until(
        "the demo window's temperature is in InfluxDB",
        lambda: flux(
            'from(bucket: "modbus") |> range(start: -5m)'
            ' |> filter(fn: (r) => r._measurement == "Simulator" and r.alias == "temperature")'
            " |> last()"
        ),
    )
    row = rows[0]
    assert row["connection"] == "Simulator (compose)" and row["device"] == "1", row
    assert row["unit"] == "°C" and row["_field"] == "value", row
    # Exported in engineering units (scale 0.1), not as the raw register.
    assert -50.0 <= float(row["_value"]) <= 150.0, row["_value"]


def mqtt() -> None:
    wait_until(
        "the exporter is connected to Mosquitto and publishing",
        lambda: (
            (s := api("GET", "/api/exporters/mqtt")["status"])["connected"] and s["points_sent"] > 0
        ),
    )
    # One message from the broker itself, through the broker's own client.
    sub = subprocess.run(
        [
            "docker", "compose", "--profile", "mqtt", "exec", "-T", "mosquitto",
            "mosquitto_sub", "-u", MQTT_USERNAME, "-P", MQTT_PASSWORD,
            "-t", "modbus-studio/Simulator (compose)/1/temperature", "-C", "1", "-W", "30",
        ],
        check=False, capture_output=True, encoding="utf-8", timeout=60,
    )  # fmt: skip
    assert sub.returncode == 0, f"mosquitto_sub failed: {sub.stderr or sub.stdout}"
    body = json.loads(sub.stdout.splitlines()[0])
    assert body["alias"] == "temperature" and body["unit"] == "°C", body
    assert body["connection"] == "Simulator (compose)" and body["device"] == 1, body
    # Published in engineering units (scale 0.1), not as the raw register.
    assert -50.0 <= body["value"] <= 150.0, body
    assert body["timestamp"].endswith("Z"), body


STEPS: dict[str, Callable[[], None]] = {
    "connectivity": connectivity,
    "persist-write": persist_write,
    "persist-check": persist_check,
    "influxdb": influxdb,
    "mqtt": mqtt,
}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "connectivity"
    if mode not in STEPS:
        print(f"usage: smoke_test.py [{' | '.join(STEPS)}]")
        return 2
    try:
        wait_until("API health", lambda: api("GET", "/api/health")["status"] == "ok")
        STEPS[mode]()
    except (AssertionError, urllib.error.URLError) as exc:
        print(f"FAIL {exc}")
        dump_state()
        return 1
    print(f"smoke test passed ({mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
