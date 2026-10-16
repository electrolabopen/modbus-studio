"""Check an installed modbus-studio package: the commands run, the UI is served and
the server polls the bundled simulator.

    pip install dist/modbus_studio-*.whl
    python .github/scripts/package_smoke.py 0.1.0

Run it outside the source tree, so the installed package is the one imported.
Standard library only; works on Linux, Windows and macOS.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as res:
        raw = res.read()
    return raw.decode() if "json" not in res.headers.get("Content-Type", "") else json.loads(raw)


def wait_until(what: str, check, timeout: float = 60.0) -> Any:
    deadline = time.monotonic() + timeout
    error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if result := check():
                print(f"ok   {what}")
                return result
        except (OSError, urllib.error.URLError, ValueError) as exc:
            error = exc
        time.sleep(0.5)
    raise SystemExit(f"FAIL {what} (last error: {error})")


def exe(name: str) -> str:
    """A console script of the package, looked up next to this Python first (where pip
    installed it), then on PATH."""
    path = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    found = shutil.which(name, path=path)
    if not found:
        raise SystemExit(f"FAIL {name} is not installed")
    return found


def command(*args: str) -> str:
    out = subprocess.run([exe(args[0]), *args[1:]], capture_output=True, text=True,
                         timeout=60, check=True)  # fmt: skip
    return out.stdout.strip()


def main() -> None:
    expected = sys.argv[1] if len(sys.argv) > 1 else None
    version = command("modbus-studio", "--version")
    print(f"ok   {version}")
    if expected and version != f"modbus-studio {expected}":
        raise SystemExit(f"FAIL expected version {expected}, got {version!r}")
    command("modbus-studio-sim", "--help")

    sim_port, app_port = free_port(), free_port()
    base = f"http://127.0.0.1:{app_port}"
    env = {**os.environ, "MODBUS_STUDIO_PORT": str(app_port)}
    for name in [k for k in env if k.startswith("MODBUS_STUDIO_") and k != "MODBUS_STUDIO_PORT"]:
        del env[name]
    with tempfile.TemporaryDirectory() as workdir:
        sim = subprocess.Popen(
            [exe("modbus-studio-sim"), "--host", "127.0.0.1", "--tcp-port", str(sim_port),
             "--rtu-tcp-port", "0"],
            cwd=workdir,
        )  # fmt: skip
        app = subprocess.Popen([exe("modbus-studio")], cwd=workdir, env=env)
        try:
            health = wait_until("the server answers", lambda: http("GET", f"{base}/api/health"))
            assert health["status"] == "ok", health
            page = http("GET", f"{base}/")
            assert "<title>modbus-studio</title>" in page, page[:200]
            print("ok   the UI is served from the package")

            http(
                "POST",
                f"{base}/api/connections",
                {"id": "sim", "type": "tcp", "host": "127.0.0.1", "port": sim_port},
            )
            http("POST", f"{base}/api/polls", {"id": "w", "connection_id": "sim", "quantity": 3})
            data = wait_until(
                "values polled from the simulator",
                # null until the first poll has finished
                lambda: (
                    (d := http("GET", f"{base}/api/polls/w/data"))
                    and d["ok"]
                    and d["stats"]["valid"] >= 3
                    and d
                ),
            )
            print(f"     {[c['value'] for c in data['cells']]}")
        finally:
            for proc in (app, sim):
                proc.terminate()
            for proc in (app, sim):
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
    print("package smoke test passed")


if __name__ == "__main__":
    main()
