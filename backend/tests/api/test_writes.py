"""Window writes as the UI does them: preview (confirmation dialog), then write."""

import pytest

from tests.api.conftest import wait_for
from tests.api.test_rest import create_poll

PREVIEW = "/api/polls/{}/write/preview"
WRITE = "/api/polls/{}/write"


def raw_at(client, poll_id, address):
    data = client.get(f"/api/polls/{poll_id}/data").json()
    cells = {c["address"]: c for c in data["cells"]} if data and data["ok"] else {}
    return cells.get(address, {}).get("raw")


def test_preview_shows_raw_registers_and_does_not_write(client, sim_conn):
    create_poll(
        client,
        id="w",
        address=110,
        quantity=4,
        formats={"110": {"dtype": "float32", "order": "CDAB", "unit": "bar"}},
    )
    before = wait_for(lambda: raw_at(client, "w", 110))
    res = client.post(PREVIEW.format("w"), json={"address": 110, "value": 1.5})
    assert res.status_code == 200, res.text
    plan = res.json()
    # 1.5f = 0x3FC00000, CDAB puts the low word first.
    assert plan["function"] == 16 and plan["values"] == [0x0000, 0x3FC0]
    assert plan["dtype"] == "float32" and plan["order"] == "CDAB" and plan["unit"] == "bar"
    assert plan["result"] == 1.5 and plan["text"] == "1.5" and not plan["rounded"]
    assert plan["device_id"] == 1 and plan["connection_id"] == "sim"
    # Nothing was sent: the next polls still read the old registers.
    client.post("/api/polls/w/reset")
    wait_for(lambda: client.get("/api/polls/w").json()["stats"]["valid"] >= 2)
    assert raw_at(client, "w", 110) == before


def test_preview_flags_rounding_and_single_vs_multiple(client, sim_conn):
    create_poll(
        client,
        id="t",
        address=120,
        quantity=2,
        formats={"120": {"dtype": "int16", "scale": 0.1, "unit": "°C"}},
    )
    plan = client.post(PREVIEW.format("t"), json={"address": 120, "value": 23.45}).json()
    assert plan["function"] == 6 and plan["values"] == [234]
    assert plan["result"] == pytest.approx(23.4) and plan["text"] == "23.4"
    assert plan["rounded"] is True
    forced = {"address": 120, "value": 23.4, "force_multiple": True}
    plan = client.post(PREVIEW.format("t"), json=forced).json()
    assert plan["function"] == 16 and plan["rounded"] is False


def test_write_returns_the_plan_and_reaches_the_device(client, sim_conn):
    create_poll(client, id="u", address=130, quantity=1, default_format={"dtype": "uint16"})
    res = client.post(WRITE.format("u"), json={"address": 130, "value": 4242})
    assert res.status_code == 200 and res.json()["values"] == [4242]
    wait_for(lambda: raw_at(client, "u", 130) == [4242])


def test_read_only_connection_rejects_writes(client, sim):
    conn = {"type": "tcp", "id": "ro", "host": "127.0.0.1", "port": sim.tcp, "read_only": True}
    assert client.post("/api/connections", json=conn).status_code == 201
    create_poll(client, id="r", connection_id="ro", address=140, quantity=1)
    for path in (PREVIEW, WRITE):
        res = client.post(path.format("r"), json={"address": 140, "value": 1})
        assert res.status_code == 403 and "read-only" in res.json()["detail"]
    raw = {"function": 6, "address": 140, "values": [1]}
    assert client.post("/api/connections/ro/write", json=raw).status_code == 403


def test_toggling_read_only_keeps_polling(client, sim):
    conn = {"type": "tcp", "id": "lk", "host": "127.0.0.1", "port": sim.tcp}
    client.post("/api/connections", json=conn)
    create_poll(client, id="k", connection_id="lk", address=150, quantity=1)
    wait_for(lambda: client.get("/api/polls/k").json()["stats"]["valid"] >= 3)

    res = client.put("/api/connections/lk", json={**conn, "read_only": True, "name": "Plant"})
    assert res.status_code == 200 and res.json()["config"]["read_only"] is True
    # Not restarted: the counters keep growing from where they were.
    assert client.get("/api/polls/k").json()["stats"]["valid"] >= 3
    assert client.post(WRITE.format("k"), json={"address": 150, "value": 1}).status_code == 403

    client.put("/api/connections/lk", json={**conn, "read_only": False})
    assert client.post(WRITE.format("k"), json={"address": 150, "value": 1}).status_code == 200
