import pytest
from starlette.websockets import WebSocketDisconnect


def receive_until(ws, predicate, limit=500):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message not received")


def test_snapshot_then_live_values(client, sim_conn):
    with client.websocket_connect("/api/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert [c["config"]["id"] for c in snapshot["connections"]] == ["sim"]
        assert snapshot["polls"] == []

        res = client.post(
            "/api/polls",
            json={"id": "live", "connection_id": "sim", "quantity": 3, "scan_rate_ms": 50},
        )
        assert res.status_code == 201
        # The change made over REST is pushed as a new snapshot.
        receive_until(ws, lambda m: m["type"] == "snapshot" and m["polls"])

        seqs = []
        for _ in range(3):
            msg = receive_until(ws, lambda m: m["type"] == "poll")
            assert msg["data"]["poll_id"] == "live" and msg["data"]["ok"]
            assert [c["address"] for c in msg["data"]["cells"]] == [0, 1, 2]
            seqs.append(msg["data"]["seq"])
        assert seqs == sorted(seqs) and len(set(seqs)) == 3

        conn = receive_until(ws, lambda m: m["type"] == "connection")
        assert conn["data"]["state"] == "connected"
        assert conn["data"]["stats"]["responses"] >= 1


def test_traffic_is_opt_in(client, sim_conn):
    client.post("/api/polls", json={"id": "t", "connection_id": "sim", "scan_rate_ms": 50})
    with client.websocket_connect("/api/ws") as ws:
        ws.receive_json()  # snapshot
        for _ in range(5):
            assert ws.receive_json()["type"] in ("poll", "connection")
        ws.send_json({"type": "subscribe", "topics": ["traffic"]})
        msg = receive_until(ws, lambda m: m["type"] == "traffic")
        assert msg["data"]["connection_id"] == "sim"
        assert msg["data"]["direction"] in ("tx", "rx")
        # Only traffic from now on (allow for messages already queued).
        later = [ws.receive_json()["type"] for _ in range(30)][-10:]
        assert set(later) == {"traffic"}


def test_ws_requires_token_message(make_client):
    client = make_client(token="t0k")
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "auth", "token": "wrong"})
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 1008

    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "auth", "token": "t0k"})
        assert ws.receive_json()["type"] == "snapshot"
