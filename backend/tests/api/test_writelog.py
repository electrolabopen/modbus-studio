"""The write log: every write sent (or attempted), with the value before and after."""

import json

from modbus_studio.core.writelog import WriteLog
from tests.api.conftest import wait_for
from tests.api.test_persistence import server
from tests.api.test_rest import create_poll


def displayed(client, poll_id, address):
    data = client.get(f"/api/polls/{poll_id}/data").json()
    cells = {c["address"]: c for c in data["cells"]} if data and data["ok"] else {}
    return cells.get(address, {}).get("text")


def test_window_write_is_logged_with_old_and_new_value(client, sim_conn):
    create_poll(
        client,
        id="w",
        address=160,
        quantity=2,
        formats={"160": {"dtype": "int16", "scale": 0.1, "unit": "°C", "alias": "setpoint"}},
    )
    client.post("/api/connections/sim/write", json={"function": 6, "address": 160, "values": [215]})
    wait_for(lambda: displayed(client, "w", 160) == "21.5")

    res = client.post("/api/polls/w/write", json={"address": 160, "value": 23.4})
    assert res.status_code == 200
    window_entry, raw_entry = client.get("/api/writes").json()[:2]
    assert window_entry["seq"] == raw_entry["seq"] + 1
    assert {k: window_entry[k] for k in ("connection_id", "device_id", "function", "address")} == {
        "connection_id": "sim",
        "device_id": 1,
        "function": 6,
        "address": 160,
    }
    assert window_entry["poll_id"] == "w" and window_entry["alias"] == "setpoint"
    assert window_entry["old"] == "21.5" and window_entry["new"] == "23.4"
    assert window_entry["unit"] == "°C" and window_entry["values"] == [234]
    assert window_entry["ok"] is True and window_entry["error"] is None
    # Raw API writes are logged too, without a window or a previous value.
    assert raw_entry["poll_id"] is None and raw_entry["old"] is None
    assert raw_entry["new"] == "215" and raw_entry["values"] == [215]


def test_rejected_write_is_logged_as_failed(client, sim_conn):
    res = client.post(
        "/api/connections/sim/write", json={"function": 6, "address": 300, "values": [1]}
    )
    assert res.status_code == 502
    [entry] = client.get("/api/writes").json()
    assert entry["ok"] is False and entry["error"] == "Illegal data address (02h)"


def test_requests_that_never_reach_the_device_are_not_logged(client, sim_conn):
    create_poll(client, id="ir", function=4, quantity=2)
    assert client.post("/api/polls/ir/write", json={"address": 0, "value": 1}).status_code == 400
    bad = {"function": 6, "address": 0, "values": [70000]}
    assert client.post("/api/connections/sim/write", json=bad).status_code == 400
    assert client.get("/api/writes").json() == []


def test_write_log_is_saved_and_reloaded(tmp_path, sim):
    path = tmp_path / "data" / "writes.jsonl"
    conn = {"type": "tcp", "id": "plc", "host": "127.0.0.1", "port": sim.tcp}
    write = {"function": 16, "address": 170, "values": [1, 2]}
    with server(write_log_file=path) as client:
        client.post("/api/connections", json=conn)
        assert client.post("/api/connections/plc/write", json=write).status_code == 204
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["values"] == [1, 2]
    with server(write_log_file=path) as client:
        client.post("/api/connections", json=conn)
        [old] = client.get("/api/writes").json()
        assert old["seq"] == 1 and old["new"] == "1 2"
        client.post("/api/connections/plc/write", json=write)
        assert [e["seq"] for e in client.get("/api/writes").json()] == [2, 1]


def test_writes_are_pushed_over_the_websocket(client, sim_conn):
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        write = {"function": 5, "address": 20, "values": [1]}
        assert client.post("/api/connections/sim/write", json=write).status_code == 204
        message = wait_for(lambda: (m := ws.receive_json())["type"] == "write" and m)
        assert message["data"]["function"] == 5 and message["data"]["address"] == 20


def test_damaged_lines_are_skipped_and_the_file_rotates(tmp_path):
    path = tmp_path / "writes.jsonl"
    log = WriteLog(path, max_bytes=300)
    fields = {"connection_id": "c", "device_id": 1, "function": 6, "address": 0, "new": "1"}
    log.record(**fields, values=[1], ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write('{"seq": 2, "trunc')  # a crash in the middle of a line
    reloaded = WriteLog(path, max_bytes=300)
    assert [e.seq for e in reloaded.entries()] == [1]
    reloaded.record(**fields, values=[2], ok=True)
    # The new entry starts on its own line instead of extending the damaged one.
    assert [e.seq for e in WriteLog(path).entries()] == [2, 1]
    for _ in range(3):
        reloaded.record(**fields, values=[1], ok=True)
    assert (tmp_path / "writes.jsonl.1").exists()
    assert [e.seq for e in reloaded.entries(2)] == [5, 4]
