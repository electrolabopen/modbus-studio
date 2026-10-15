"""WebSocket push channel.

Server -> client messages (JSON objects with a ``type``):

- ``snapshot``: every connection and polling window with its latest data.
  Sent on connect and after any change made through the REST API.
- ``poll``: a new result of one polling window (decoded cells + counters).
- ``connection``: state and counters of a connection, after each of its polls.
- ``traffic``: one raw frame. Only sent to clients subscribed to ``traffic``.
- ``write``: one new entry of the write log.

Client -> server messages:

- ``{"type": "auth", "token": "..."}``: must be the first message when the
  server has a token. The token is not sent in the URL so it does not end up
  in access logs.
- ``{"type": "subscribe", "topics": ["polls", "connections", "traffic"]}``
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from ..config import Settings, get_settings
from ..core.poller import PollResult
from ..core.studio import Studio
from ..core.traffic import TrafficEntry
from ..models.views import WriteLogEntry

log = logging.getLogger(__name__)

TOPICS = frozenset({"polls", "connections", "traffic", "writes"})
DEFAULT_TOPICS = frozenset({"polls", "connections", "writes"})
AUTH_TIMEOUT_S = 5.0

Message = dict[str, Any]


class Client:
    def __init__(self, maxsize: int = 2000) -> None:
        self.queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=maxsize)
        self.topics: set[str] = set(DEFAULT_TOPICS)

    def offer(self, message: Message) -> None:
        """Queue a message; a client that cannot keep up loses the oldest ones."""
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.queue.put_nowait(message)


class Hub:
    def __init__(self, studio: Studio) -> None:
        self.studio = studio
        self.clients: set[Client] = set()
        self._unsubscribe = [
            studio.polls.subscribe(self._on_poll),
            studio.traffic.subscribe(self._on_traffic),
            studio.write_log.subscribe(self._on_write),
        ]

    def close(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()

    def _publish(self, topic: str | None, message: Message) -> None:
        for client in self.clients:
            if topic is None or topic in client.topics:
                client.offer(message)

    def _on_poll(self, result: PollResult) -> None:
        if not self.clients:
            return
        try:
            task = self.studio.polls.get(result.poll_id)
        except KeyError:  # removed while the request was in flight
            return
        data = self.studio.poll_data(task, result)
        self._publish("polls", {"type": "poll", "data": data.model_dump(mode="json")})
        conn = self.studio.connection_view(task.definition.connection_id)
        self._publish("connections", {"type": "connection", "data": conn.model_dump(mode="json")})

    def _on_traffic(self, entry: TrafficEntry) -> None:
        if not self.clients:
            return
        view = self.studio.traffic_view(entry)
        self._publish("traffic", {"type": "traffic", "data": view.model_dump(mode="json")})

    def _on_write(self, entry: WriteLogEntry) -> None:
        self._publish("writes", {"type": "write", "data": entry.model_dump(mode="json")})

    def snapshot(self) -> Message:
        return {
            "type": "snapshot",
            "connections": [c.model_dump(mode="json") for c in self.studio.list_connections()],
            "polls": [p.model_dump(mode="json") for p in self.studio.list_polls()],
        }

    def publish_snapshot(self) -> None:
        if self.clients:
            self._publish(None, self.snapshot())


router = APIRouter(prefix="/api")


async def _authenticate(websocket: WebSocket, settings: Settings) -> bool:
    if not settings.token:
        return True
    try:
        message = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT_S)
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        return False
    token = message.get("token") if isinstance(message, dict) else None
    return (
        isinstance(message, dict)
        and message.get("type") == "auth"
        and isinstance(token, str)
        and secrets.compare_digest(token.encode(), settings.token.encode())
    )


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    hub: Hub = websocket.app.state.hub
    await websocket.accept()
    if not await _authenticate(websocket, settings):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid token")
        return

    client = Client()
    client.offer(hub.snapshot())
    hub.clients.add(client)

    async def sender() -> None:
        while True:
            await websocket.send_json(await client.queue.get())

    send_task = asyncio.create_task(sender())
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("type") == "subscribe":
                topics = message.get("topics")
                if isinstance(topics, list):
                    client.topics = {t for t in topics if t in TOPICS}
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        hub.clients.discard(client)
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await send_task
