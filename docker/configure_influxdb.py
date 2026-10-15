"""Point modbus-studio's InfluxDB exporter at the compose InfluxDB (profile "influxdb").

Runs once after both are up. It only fills in an exporter that has never been
configured, so settings changed later in the UI or the API are left alone.

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


def main() -> int:
    current = api("GET", "/api/exporters/influxdb")["config"]
    if current["enabled"] or current["token_set"]:
        print("InfluxDB exporter already configured; leaving it as it is")
        return 0
    api(
        "PUT",
        "/api/exporters/influxdb",
        {
            "enabled": True,
            "url": os.environ.get("INFLUXDB_URL", "http://influxdb:8086"),
            "org": os.environ["INFLUXDB_ORG"],
            "bucket": os.environ["INFLUXDB_BUCKET"],
            "token": os.environ["INFLUXDB_TOKEN"],
        },
    )
    print("InfluxDB exporter configured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
