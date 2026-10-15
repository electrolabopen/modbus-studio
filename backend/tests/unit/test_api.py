import pytest
from fastapi.testclient import TestClient

from modbus_studio.config import Settings, get_settings
from modbus_studio.main import create_app


@pytest.fixture
def make_client():
    def factory(**settings):
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: Settings(**settings)
        return TestClient(app)

    return factory


def test_health_is_public(make_client):
    with make_client(token="s3cret") as client:
        res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_no_token_configured_allows_access(make_client):
    with make_client() as client:
        assert client.get("/api/info").status_code == 200


def test_token_is_enforced(make_client):
    with make_client(token="s3cret") as client:
        assert client.get("/api/info").status_code == 401
        assert client.get("/api/info", headers={"Authorization": "Bearer nope"}).status_code == 401
        res = client.get("/api/info", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200
    assert res.json() == {"version": res.json()["version"], "connections": 0, "polls": 0}


def test_default_bind_is_loopback(monkeypatch):
    monkeypatch.delenv("MODBUS_STUDIO_HOST", raising=False)
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1" and settings.is_loopback
    assert settings.token is None
