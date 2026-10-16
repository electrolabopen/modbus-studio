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


MQTT = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 1,  # nothing listens there
    "username": "modbus",
    "password": "s3cret",
}


def test_mqtt_defaults_to_disabled(client):
    body = client.get("/api/exporters/mqtt").json()
    assert body["config"]["enabled"] is False and body["config"]["password_set"] is False
    assert body["config"]["topic"] == "modbus-studio/{connection}/{device}/{alias}"
    assert body["status"]["state"] == "disabled" and body["status"]["connected"] is False


def test_the_mqtt_password_is_never_returned(client):
    res = client.put("/api/exporters/mqtt", json=MQTT)
    assert res.status_code == 200, res.text
    assert "s3cret" not in res.text and "s3cret" not in client.get("/api/exporters/mqtt").text
    assert res.json()["config"]["password_set"] is True
    assert res.json()["status"]["state"] in ("idle", "error")  # no broker there


def test_omitting_the_mqtt_password_keeps_it_and_an_empty_one_removes_it(client):
    client.put("/api/exporters/mqtt", json=MQTT)
    body = client.put("/api/exporters/mqtt", json={**MQTT, "password": None, "qos": 1}).json()
    assert body["config"]["password_set"] is True and body["config"]["qos"] == 1
    body = client.put("/api/exporters/mqtt", json={**MQTT, "password": ""}).json()
    assert body["config"]["password_set"] is False


def test_mqtt_settings_are_validated(client):
    res = client.put("/api/exporters/mqtt", json={**MQTT, "topic": "plant/{name}"})
    assert res.status_code == 422 and "unknown placeholder" in res.text
    res = client.put("/api/exporters/mqtt", json={**MQTT, "topic": "plant/#"})
    assert res.status_code == 422
    assert client.put("/api/exporters/mqtt", json={**MQTT, "qos": 3}).status_code == 422
    assert client.put("/api/exporters/mqtt", json={**MQTT, "port": 0}).status_code == 422


def test_downloaded_workspace_has_the_mqtt_settings_but_not_the_password(client):
    client.put("/api/exporters/mqtt", json=MQTT)
    workspace = client.get("/api/workspace").json()
    assert workspace["exporters"]["mqtt"]["username"] == "modbus"
    assert workspace["exporters"]["mqtt"]["password"] is None
    workspace["exporters"]["mqtt"]["topic"] = "imported/{alias}"
    res = client.post("/api/workspace?mode=replace", json=workspace)
    assert res.status_code == 200, res.text
    config = client.get("/api/exporters/mqtt").json()["config"]
    assert config["topic"] == "imported/{alias}" and config["password_set"] is True


def test_mqtt_settings_survive_a_restart(tmp_path):
    state = tmp_path / "workspace.json"
    with server(state_file=state) as client:
        client.put("/api/exporters/mqtt", json=MQTT)
    saved = json.loads(state.read_text(encoding="utf-8"))["exporters"]["mqtt"]
    assert saved["password"] == "s3cret"
    with server(state_file=state) as client:
        config = client.get("/api/exporters/mqtt").json()["config"]
        assert config["enabled"] is True and config["password_set"] is True


def test_all_exporters_at_once(client):
    client.put("/api/exporters/influxdb", json=INFLUX)
    body = client.get("/api/exporters").json()
    assert body["influxdb"]["config"]["token_set"] is True
    assert body["mqtt"]["status"]["state"] == "disabled"
    assert "s3cret" not in client.get("/api/exporters").text


def test_testing_settings_does_not_apply_them(client):
    res = client.post("/api/exporters/mqtt/test", json={**MQTT, "enabled": False})
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is False and "cannot connect to 127.0.0.1:1" in res.json()["message"]
    assert client.get("/api/exporters/mqtt").json()["config"]["enabled"] is False
    res = client.post("/api/exporters/influxdb/test", json={**INFLUX, "token": None})
    assert res.json()["ok"] is False and res.json()["message"] == "missing: token"
    assert client.post("/api/exporters/mqtt/test", json={"topic": "a/#"}).status_code == 422
