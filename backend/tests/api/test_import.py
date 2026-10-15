"""Workspace export/import and CSV register maps."""

from pathlib import Path

import pytest

from modbus_studio.simulator import CONST_INT32, CONST_UINT32
from tests.api.conftest import wait_for
from tests.api.test_persistence import server
from tests.api.test_rest import create_poll

EXAMPLE = Path(__file__).parents[3] / "docs" / "examples" / "simulator-map.csv"


def import_csv(client, poll_id, text):
    return client.post(f"/api/polls/{poll_id}/register-map", json={"csv": text})


def cells(client, poll_id):
    data = client.get(f"/api/polls/{poll_id}/data").json()
    return data and data["ok"] and {c["address"]: c for c in data["cells"]}


def test_simulator_example_decodes_the_simulator(client, sim_conn):
    create_poll(client, id="sim", address=0, quantity=28)
    res = import_csv(client, "sim", EXAMPLE.read_text(encoding="utf-8"))
    assert res.status_code == 200, res.text

    by = wait_for(lambda: (c := cells(client, "sim")) and c[24]["value"] is not None and c)
    assert by[24]["value"] == CONST_INT32 and by[24]["alias"] == "int32 constant"
    assert by[26]["value"] == CONST_UINT32
    assert by[2]["unit"] == "°C" and by[2]["alias"] == "temperature"
    # The same sine wave stored in four byte orders and as float64 reads the same.
    sines = [by[a]["value"] for a in (10, 12, 14, 16)]
    assert len(set(sines)) == 1
    assert by[20]["value"] == pytest.approx(sines[0], abs=1e-4)


def test_csv_gives_the_same_table_as_configuring_by_hand(client, sim_conn):
    create_poll(client, id="csv", address=0, quantity=28)
    create_poll(client, id="hand", address=0, quantity=28)
    import_csv(client, "csv", EXAMPLE.read_text(encoding="utf-8"))
    patches = [
        {"start": 0, "end": 1, "dtype": "uint16"},
        {"start": 2, "end": 2, "scale": 0.1, "unit": "°C"},
        {"start": 10, "end": 16, "dtype": "float32"},
        {"start": 12, "end": 12, "order": "CDAB"},
        {"start": 14, "end": 14, "order": "BADC"},
        {"start": 16, "end": 16, "order": "DCBA"},
        {"start": 20, "end": 20, "dtype": "float64"},
        {"start": 24, "end": 24, "dtype": "int32"},
        {"start": 26, "end": 26, "dtype": "uint32", "order": "CDAB"},
    ]
    aliases = {
        0: "counter",
        1: "sawtooth",
        2: "temperature",
        10: "sine ABCD",
        12: "sine CDAB",
        14: "sine BADC",
        16: "sine DCBA",
        20: "sine float64",
        24: "int32 constant",
        26: "uint32 constant",
    }
    for body in patches:
        assert client.patch("/api/polls/hand/formats", json=body).status_code == 200
    for address, alias in aliases.items():
        body = {"start": address, "end": address, "alias": alias}
        assert client.patch("/api/polls/hand/formats", json=body).status_code == 200

    def formats(poll_id):
        return client.get(f"/api/polls/{poll_id}").json()["definition"]["formats"]

    assert formats("csv") == formats("hand")


def test_invalid_csv_changes_nothing_and_lists_every_line(client, sim_conn):
    create_poll(client, id="w", address=0, quantity=10, formats={"0": {"alias": "keep"}})
    text = "address,type\n2,float32\n9,float32\n40001,int16\n"
    res = import_csv(client, "w", text)
    assert res.status_code == 400
    assert res.json()["errors"] == [
        {"line": 3, "message": "address 9-10 is outside this window (0-9)"},
        {
            "line": 4,
            "message": "address 40001 is outside this window (0-9); use 0-based protocol "
            "addresses, not 3xxxx/4xxxx numbers",
        },
    ]
    # 40001 is far beyond what one FC03 request can read: no window to offer.
    assert res.json()["fit"] is None
    assert client.get("/api/polls/w").json()["definition"]["formats"]["0"]["alias"] == "keep"
    res = import_csv(client, "w", "address,type\nx,int16\n")
    assert res.status_code == 400 and res.json()["errors"][0]["line"] == 2


def test_a_window_too_small_can_grow_to_fit_the_map(client, sim_conn):
    create_poll(client, id="small", address=10, quantity=10)
    example = EXAMPLE.read_text(encoding="utf-8")
    res = import_csv(client, "small", example)
    assert res.status_code == 400
    assert res.json()["fit"] == {"address": 0, "quantity": 28}
    assert client.get("/api/polls/small").json()["definition"]["quantity"] == 10

    res = client.post("/api/polls/small/register-map?fit=true", json={"csv": example})
    assert res.status_code == 200, res.text
    d = res.json()["definition"]
    assert (d["address"], d["quantity"]) == (0, 28)
    assert d["formats"]["26"] == {
        "dtype": "uint32",
        "order": "CDAB",
        "scale": 1.0,
        "unit": "",
        "alias": "uint32 constant",
    }
    by = wait_for(lambda: (c := cells(client, "small")) and len(c) >= 27 and c)
    assert by[0]["alias"] == "counter"


def test_no_window_is_offered_when_resizing_would_not_fix_the_map(client, sim_conn):
    create_poll(client, id="c", function=1, address=0, quantity=8)
    # Row 20 is outside, but row 3 has a unit, which a coil window never takes.
    res = import_csv(client, "c", "address,alias,unit\n3,pump,bar\n20,valve,\n")
    assert res.status_code == 400 and res.json()["fit"] is None
    create_poll(client, id="r", address=0, quantity=100)
    # Growing to 0-129 would pass the 125 registers one FC03 request can read.
    assert import_csv(client, "r", "address,type\n128,float32\n").json()["fit"] is None
    res = client.post("/api/polls/r/register-map?fit=true", json={"csv": "address\n128\n"})
    assert res.status_code == 400
    assert client.get("/api/polls/r").json()["definition"]["quantity"] == 100


def test_rows_hidden_by_a_wide_window_default_are_rejected(client, sim_conn):
    create_poll(client, id="f", address=0, quantity=4, default_format={"dtype": "float32"})
    res = import_csv(client, "f", "address,type\n1,int16\n")
    assert res.status_code == 400
    assert "covered by the window's default float32 at 0" in res.json()["errors"][0]["message"]
    assert import_csv(client, "f", "address,type\n0,float32\n2,int16\n3,int16\n").status_code == 200


def test_bit_windows_take_aliases_only(client, sim_conn):
    create_poll(client, id="c", function=1, address=0, quantity=8)
    assert import_csv(client, "c", "address,alias\n3,pump\n").status_code == 200
    assert client.get("/api/polls/c").json()["definition"]["formats"]["3"]["alias"] == "pump"
    res = import_csv(client, "c", "address,alias,unit\n3,pump,bar\n")
    assert res.status_code == 400 and "only take an alias" in res.json()["errors"][0]["message"]


def test_workspace_round_trip(sim):
    conn = {"type": "tcp", "id": "plc", "host": "127.0.0.1", "port": sim.tcp, "read_only": True}
    with server() as a:
        a.post("/api/connections", json=conn)
        create_poll(a, id="w", connection_id="plc", address=0, quantity=28)
        import_csv(a, "w", EXAMPLE.read_text(encoding="utf-8"))
        exported = a.get("/api/workspace").json()
    assert exported["version"] == 1 and exported["connections"][0]["read_only"] is True

    with server() as b:
        b.post("/api/connections", json={"type": "tcp", "id": "other", "host": "x"})
        res = b.post("/api/workspace", json=exported)  # default: replace
        assert res.status_code == 200 and res.json() == {"connections": 1, "polls": 1}
        assert b.get("/api/workspace").json() == exported
        by = wait_for(lambda: (c := cells(b, "w")) and c)
        assert by[24]["value"] == CONST_INT32


def test_merge_refuses_ids_in_use(client, sim_conn):
    ws = {
        "connections": [{"type": "tcp", "id": "sim", "host": "127.0.0.1"}],
        "polls": [{"id": "n", "connection_id": "sim"}],
    }
    res = client.post("/api/workspace?mode=merge", json=ws)
    assert res.status_code == 409 and "already in use: sim" in res.json()["detail"]
    ws["connections"][0]["id"] = ws["polls"][0]["connection_id"] = "sim2"
    assert client.post("/api/workspace?mode=merge", json=ws).status_code == 200
    ids = sorted(c["config"]["id"] for c in client.get("/api/connections").json())
    assert ids == ["sim", "sim2"]


def test_invalid_workspace_is_rejected_before_touching_the_session(client, sim_conn):
    bad = {"connections": [], "polls": [{"id": "x", "connection_id": "missing"}]}
    assert client.post("/api/workspace", json=bad).status_code == 422
    assert [c["config"]["id"] for c in client.get("/api/connections").json()] == ["sim"]
