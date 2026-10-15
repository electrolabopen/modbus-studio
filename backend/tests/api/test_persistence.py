import json
from contextlib import contextmanager

from fastapi.testclient import TestClient

from modbus_studio.config import Settings, get_settings
from modbus_studio.core.persistence import AutoSaver, StateFile
from modbus_studio.main import create_app
from modbus_studio.models.workspace import Workspace


@contextmanager
def server(**settings):
    """One server lifetime: leaving the block is a container restart."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, **settings)
    with TestClient(app) as client:
        yield client


def ids(client: TestClient) -> tuple[list[str], list[str]]:
    conns = [c["config"]["id"] for c in client.get("/api/connections").json()]
    polls = [p["definition"]["id"] for p in client.get("/api/polls").json()]
    return conns, polls


def test_workspace_survives_restart(tmp_path, sim):
    state = tmp_path / "data" / "workspace.json"
    with server(state_file=state) as client:
        assert ids(client) == ([], [])
        res = client.post(
            "/api/connections",
            json={"type": "tcp", "id": "plc", "host": "127.0.0.1", "port": sim.tcp},
        )
        assert res.status_code == 201, res.text
        res = client.post(
            "/api/polls",
            json={
                "id": "w1",
                "connection_id": "plc",
                "address": 2,
                "formats": {"2": {"dtype": "int16", "scale": 0.1, "unit": "°C", "alias": "temp"}},
            },
        )
        assert res.status_code == 201, res.text
    with server(state_file=state) as client:
        assert ids(client) == (["plc"], ["w1"])
        fmt = client.get("/api/polls/w1").json()["definition"]["formats"]["2"]
        assert fmt["alias"] == "temp" and fmt["unit"] == "°C"
    assert not list(state.parent.glob(".*.tmp"))


def test_saved_state_wins_over_seed(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps({"connections": [{"type": "tcp", "id": "demo", "host": "simulator"}]}),
        encoding="utf-8",
    )
    state = tmp_path / "workspace.json"
    with server(state_file=state, workspace=seed) as client:
        assert ids(client) == (["demo"], [])
        assert client.delete("/api/connections/demo").status_code == 204
    # The demo connection the user deleted must not come back.
    with server(state_file=state, workspace=seed) as client:
        assert ids(client) == ([], [])


def test_unreadable_state_is_moved_aside(tmp_path):
    state = tmp_path / "workspace.json"
    state.write_text("{not json", encoding="utf-8")
    with server(state_file=state) as client:
        assert ids(client) == ([], [])
    [aside] = tmp_path.glob("workspace.json.invalid-*")
    assert aside.read_text(encoding="utf-8") == "{not json"
    assert Workspace.load(state) == Workspace()


def test_without_state_file_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with server() as client:
        res = client.post("/api/connections", json={"type": "tcp", "id": "plc", "host": "plc"})
        assert res.status_code == 201, res.text
    assert list(tmp_path.iterdir()) == []


async def test_changes_are_coalesced(tmp_path):
    import asyncio

    saves: list[Workspace] = []

    class Recording(StateFile):
        def save(self, workspace: Workspace) -> None:
            saves.append(workspace)
            super().save(workspace)

    saver = AutoSaver(Recording(tmp_path / "w.json"), Workspace, delay_s=0.05)
    for _ in range(5):
        saver.schedule()
    await asyncio.sleep(0.15)
    assert len(saves) == 1
    saver.schedule()
    saver.flush()  # shutdown: write now and drop the pending timer
    await asyncio.sleep(0.1)
    assert len(saves) == 2
