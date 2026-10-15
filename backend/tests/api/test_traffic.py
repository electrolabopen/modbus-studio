"""Traffic entries describe each frame for the monitor's filters."""

import pytest

from tests.api.conftest import wait_for
from tests.api.test_rest import create_poll


@pytest.mark.parametrize("kind", ["tcp", "rtu_over_tcp"])
def test_frames_are_described(client, sim, kind):
    port = sim.tcp if kind == "tcp" else sim.rtu_tcp
    conn = {"type": kind, "id": "c", "host": "127.0.0.1", "port": port}
    assert client.post("/api/connections", json=conn).status_code == 201
    create_poll(client, id="ok", connection_id="c", device_id=2, address=0, quantity=2)
    create_poll(client, id="bad", connection_id="c", address=195, quantity=10)

    def frames():
        entries = client.get("/api/traffic", params={"connection_id": "c"}).json()
        rx = [e for e in entries if e["direction"] == "rx"]
        return {e["exception_code"] for e in rx} >= {None, 2} and entries

    entries = wait_for(frames)
    for e in entries:
        assert e["function"] == 3 and e["error"] is None
        assert (e["transaction_id"] is not None) == (kind == "tcp")
    exception = next(e for e in entries if e["exception_code"] == 2)
    assert exception["direction"] == "rx" and exception["device_id"] == 1
    assert any(e["device_id"] == 2 for e in entries)
