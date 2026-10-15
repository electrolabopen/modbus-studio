import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from modbus_studio.models.workspace import Workspace
from tests.api.conftest import wait_for


def write_workspace(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "workspace.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def demo(port: int) -> dict:
    return {
        "version": 1,
        "connections": [{"type": "tcp", "id": "sim", "host": "127.0.0.1", "port": port}],
        "polls": [{"id": "w1", "connection_id": "sim", "address": 0, "quantity": 3}],
    }


def test_workspace_is_loaded_at_startup(make_client, sim, tmp_path):
    client = make_client(workspace=write_workspace(tmp_path, demo(sim.tcp)))
    [conn] = client.get("/api/connections").json()
    assert conn["config"]["id"] == "sim"
    data = wait_for(lambda: client.get("/api/polls/w1/data").json())
    assert data["ok"] and len(data["cells"]) == 3


def test_unreachable_connection_reports_why(make_client, tmp_path):
    ws = demo(5020)
    ws["connections"][0]["host"] = "modbus-sim.invalid"
    client = make_client(workspace=write_workspace(tmp_path, ws))
    data = wait_for(lambda: client.get("/api/polls/w1/data").json())
    assert data["error"] == "cannot resolve host 'modbus-sim.invalid'"
    [conn] = client.get("/api/connections").json()
    assert conn["last_error"] == data["error"]


def test_dangling_poll_reference_is_rejected():
    ws = demo(5020)
    ws["polls"][0]["connection_id"] = "nope"
    with pytest.raises(ValidationError, match="unknown connection 'nope'"):
        Workspace.model_validate(ws)


def test_bundled_compose_workspace_is_valid():
    path = Path(__file__).parents[3] / "docker" / "demo-workspace.json"
    ws = Workspace.load(path)
    assert [c.id for c in ws.connections] == ["simulator"]
