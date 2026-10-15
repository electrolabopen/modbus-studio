import json

from .test_persistence import server

INFLUX = {
    "enabled": True,
    "url": "http://influxdb:8086",
    "org": "plant",
    "bucket": "modbus",
    "token": "s3cret",
}


def test_influxdb_defaults_to_disabled(client):
    body = client.get("/api/exporters/influxdb").json()
    assert body["config"]["enabled"] is False and body["config"]["token_set"] is False
    assert body["status"]["state"] == "disabled"


def test_the_token_is_never_returned(client):
    res = client.put("/api/exporters/influxdb", json=INFLUX)
    assert res.status_code == 200, res.text
    assert "s3cret" not in res.text and "s3cret" not in client.get("/api/exporters/influxdb").text
    assert res.json()["config"]["token_set"] is True
    # The exporter is running; with no InfluxDB there it has nothing to send yet.
    assert res.json()["status"]["state"] == "idle"


def test_omitting_the_token_keeps_it_and_an_empty_one_removes_it(client):
    client.put("/api/exporters/influxdb", json=INFLUX)
    body = client.put("/api/exporters/influxdb", json={**INFLUX, "token": None, "bucket": "b2"})
    assert body.json()["config"]["token_set"] is True
    assert body.json()["config"]["bucket"] == "b2"
    body = client.put("/api/exporters/influxdb", json={**INFLUX, "token": ""}).json()
    assert body["config"]["token_set"] is False
    assert body["status"]["state"] == "incomplete"


def test_settings_are_validated(client):
    res = client.put("/api/exporters/influxdb", json={**INFLUX, "url": "influxdb:8086"})
    assert res.status_code == 422
    assert "http://" in res.text
    res = client.put("/api/exporters/influxdb", json={**INFLUX, "flush_interval_ms": 5})
    assert res.status_code == 422


def test_downloaded_workspace_has_the_settings_but_not_the_token(client):
    client.put("/api/exporters/influxdb", json=INFLUX)
    workspace = client.get("/api/workspace").json()
    assert workspace["exporters"]["influxdb"]["bucket"] == "modbus"
    assert workspace["exporters"]["influxdb"]["token"] is None
    # Importing it back (replace) keeps the token the session already has.
    workspace["exporters"]["influxdb"]["bucket"] = "imported"
    res = client.post("/api/workspace?mode=replace", json=workspace)
    assert res.status_code == 200, res.text
    config = client.get("/api/exporters/influxdb").json()["config"]
    assert config["bucket"] == "imported" and config["token_set"] is True


def test_merging_a_workspace_keeps_the_exporter_settings(client):
    client.put("/api/exporters/influxdb", json=INFLUX)
    other = {"version": 1, "exporters": {"influxdb": {**INFLUX, "bucket": "other"}}}
    assert client.post("/api/workspace?mode=merge", json=other).status_code == 200
    assert client.get("/api/exporters/influxdb").json()["config"]["bucket"] == "modbus"


def test_settings_and_token_survive_a_restart(tmp_path):
    state = tmp_path / "workspace.json"
    with server(state_file=state) as client:
        client.put("/api/exporters/influxdb", json=INFLUX)
    # The state file keeps the token, so the exporter starts again on its own.
    assert json.loads(state.read_text(encoding="utf-8"))["exporters"]["influxdb"]["token"] == (
        "s3cret"
    )
    with server(state_file=state) as client:
        body = client.get("/api/exporters/influxdb").json()
        assert body["config"]["enabled"] is True and body["config"]["token_set"] is True
        assert body["status"]["state"] == "idle"


def test_old_workspace_files_load_without_exporters(client):
    res = client.post("/api/workspace?mode=replace", json={"version": 1, "connections": []})
    assert res.status_code == 200, res.text
    assert client.get("/api/exporters/influxdb").json()["config"]["enabled"] is False
