"""Per-cell and per-range display formats, and aliases (PATCH /api/polls/{id}/formats)."""

from tests.api.conftest import wait_for
from tests.api.test_rest import create_poll

URL = "/api/polls/{}/formats"


def patch(client, poll_id, **body):
    return client.patch(URL.format(poll_id), json=body)


def formats(client, poll_id):
    return client.get(f"/api/polls/{poll_id}").json()["definition"]["formats"]


def test_range_steps_by_value_size(client, sim_conn):
    create_poll(client, id="f", address=10, quantity=8)
    res = patch(client, "f", start=10, end=17, dtype="float32", order="CDAB")
    assert res.status_code == 200, res.text
    assert sorted(formats(client, "f"), key=int) == ["10", "12", "14", "16"]

    # The simulator holds the same sine wave at 10 (ABCD) and 12 (CDAB): with one
    # format for all four, only the CDAB copy decodes to a sane value.
    def cells():
        data = client.get("/api/polls/f/data").json()
        return data and data["ok"] and {c["address"]: c for c in data["cells"]}

    by_addr = wait_for(lambda: (c := cells()) and c[12]["value"] is not None and c)
    assert [by_addr[a]["covered_by"] for a in (11, 13, 15, 17)] == [10, 12, 14, 16]
    assert -100 <= by_addr[12]["value"] <= 100


def test_omitted_fields_are_kept_per_cell(client, sim_conn):
    create_poll(client, id="p", address=100, quantity=4)
    patch(client, "p", start=100, end=100, dtype="float32")
    patch(client, "p", start=102, end=103, scale=0.1)
    res = patch(client, "p", start=100, end=103, unit="bar")
    assert res.status_code == 200, res.text
    f = formats(client, "p")
    assert f["100"]["dtype"] == "float32" and f["100"]["unit"] == "bar"
    assert f["102"]["scale"] == 0.1 and f["103"]["scale"] == 0.1 and f["103"]["unit"] == "bar"


def test_alias_is_per_cell(client, sim_conn):
    create_poll(client, id="a", address=0, quantity=3)
    assert patch(client, "a", start=2, end=2, alias="temperature").status_code == 200
    assert formats(client, "a") == {
        "2": {"dtype": "int16", "order": "ABCD", "scale": 1.0, "unit": "", "alias": "temperature"}
    }
    data = wait_for(lambda: client.get("/api/polls/a/data").json())
    assert data["cells"][2]["alias"] == "temperature"
    assert patch(client, "a", start=0, end=1, alias="x").status_code == 422


def test_rejects_ranges_that_do_not_fit(client, sim_conn):
    create_poll(client, id="r", address=20, quantity=4)
    patch(client, "r", start=20, end=20, dtype="float32")
    res = patch(client, "r", start=21, end=22, dtype="int16")
    assert res.status_code == 400
    assert res.json()["detail"] == "address 21 is part of the value at 20; start the range there"
    res = patch(client, "r", start=23, end=23, dtype="float32")
    assert res.status_code == 400 and "past the end of the window (23)" in res.json()["detail"]
    assert patch(client, "r", start=19, end=20, dtype="int16").status_code == 400
    assert patch(client, "r", start=22, end=21, unit="x").status_code == 422


def test_reset_and_tidy_up(client, sim_conn):
    create_poll(client, id="t", address=0, quantity=4)
    patch(client, "t", start=0, end=3, dtype="uint16", unit="rpm")
    assert len(formats(client, "t")) == 4
    patch(client, "t", start=2, end=3, reset=True)
    assert sorted(formats(client, "t")) == ["0", "1"]
    # Setting a cell back to the window default removes its entry.
    patch(client, "t", start=0, end=1, dtype="int16", unit="")
    assert formats(client, "t") == {}


def test_a_new_wide_value_swallows_the_cells_it_covers(client, sim_conn):
    create_poll(client, id="s", address=0, quantity=4)
    patch(client, "s", start=1, end=1, alias="old")
    patch(client, "s", start=0, end=0, dtype="int32")
    assert sorted(formats(client, "s")) == ["0"]


def test_bit_windows_take_only_aliases(client, sim_conn):
    create_poll(client, id="b", function=1, address=0, quantity=8)
    assert patch(client, "b", start=3, end=3, alias="pump").status_code == 200
    assert formats(client, "b")["3"]["alias"] == "pump"
    res = patch(client, "b", start=0, end=7, dtype="uint16")
    assert res.status_code == 400 and "only take an alias" in res.json()["detail"]


def test_format_change_does_not_restart_polling(client, sim_conn):
    create_poll(client, id="k", address=0, quantity=2)
    wait_for(lambda: client.get("/api/polls/k").json()["stats"]["polls"] >= 3)
    patch(client, "k", start=0, end=0, dtype="uint16")
    assert client.get("/api/polls/k").json()["stats"]["polls"] >= 3
