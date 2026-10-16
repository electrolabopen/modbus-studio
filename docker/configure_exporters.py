"""Point modbus-studio's exporters at the compose InfluxDB or Mosquitto.

    python configure_exporters.py influxdb   # profile "influxdb"
    python configure_exporters.py mqtt       # profile "mqtt"

Runs once after modbus-studio is up. It only fills in an exporter that has never
been configured, so settings changed later in the UI or the API are left alone.

Standard library only: it runs in the modbus-studio image.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get("MODBUS_STUDIO_URL", "http://modbus-studio:8000").rstrip("/")
API_TOKEN = os.environ.get("MODBUS_STUDIO_TOKEN") or None


def api(method: str, path: str, body: object = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if API_TOKEN:
        req.add_header("Authorization", f"Bearer {API_TOKEN}")
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def influxdb() -> dict:
    return {
        "enabled": True,
        "url": os.environ.get("INFLUXDB_URL", "http://influxdb:8086"),
        "org": os.environ["INFLUXDB_ORG"],
        "bucket": os.environ["INFLUXDB_BUCKET"],
        "token": os.environ["INFLUXDB_TOKEN"],
    }


def mqtt() -> dict:
    return {
        "enabled": True,
        "host": os.environ.get("MQTT_HOST", "mosquitto"),
        "port": int(os.environ.get("MQTT_PORT", "1883")),
        "username": os.environ["MQTT_USERNAME"],
        "password": os.environ["MQTT_PASSWORD"],
    }


EXPORTERS = {"influxdb": (influxdb, "token_set"), "mqtt": (mqtt, "password_set")}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in EXPORTERS:
        print(f"usage: {sys.argv[0]} {{{','.join(EXPORTERS)}}}", file=sys.stderr)
        return 2
    name = sys.argv[1]
    settings, secret_set = EXPORTERS[name]
    path = f"/api/exporters/{name}"
    current = api("GET", path)["config"]
    if current["enabled"] or current[secret_set]:
        print(f"{name} exporter already configured; leaving it as it is")
        return 0
    api("PUT", path, settings())
    print(f"{name} exporter configured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
