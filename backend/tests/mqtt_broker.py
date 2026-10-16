"""A minimal MQTT 3.1.1 broker for tests: records what clients publish.

It speaks just enough of the protocol for a publisher: CONNECT (with an optional
user name and password check), PUBLISH at QoS 0, 1 and 2, PINGREQ and DISCONNECT.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    topic: str
    payload: bytes
    qos: int
    retain: bool


class FakeBroker:
    def __init__(self, users: dict[str, str] | None = None, hang_up: bool = False) -> None:
        self.users = users  # None: anyone may connect
        # Close every connection without answering, like a TLS port spoken to in clear.
        self.hang_up = hang_up
        self.messages: list[Message] = []
        self.client_ids: list[str] = []
        self.port = 0
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self, port: int = 0) -> FakeBroker:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        """Close the listening socket and drop every client, like a broker crash."""
        if self._server is None:
            return
        self._server.close()
        for writer in list(self._writers):
            writer.close()
        await self._server.wait_closed()
        self._server = None

    async def wait_for(self, count: int, timeout: float = 10.0) -> list[Message]:
        deadline = asyncio.get_running_loop().time() + timeout
        while len(self.messages) < count:
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"{len(self.messages)} messages, expected {count}")
            await asyncio.sleep(0.02)
        return self.messages

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        if self.hang_up:
            writer.close()
            return
        try:
            while True:
                first = (await reader.readexactly(1))[0]
                body = await reader.readexactly(await _read_length(reader))
                kind = first >> 4
                if kind == 1:  # CONNECT
                    accepted = self._connect(body)
                    writer.write(bytes([0x20, 2, 0, 0 if accepted else 4]))
                    if not accepted:
                        await writer.drain()
                        return
                elif kind == 3:  # PUBLISH
                    qos, retain = (first >> 1) & 3, bool(first & 1)
                    size = int.from_bytes(body[:2], "big")
                    topic, rest = body[2 : 2 + size].decode(), body[2 + size :]
                    if qos:
                        mid, rest = rest[:2], rest[2:]
                        writer.write(bytes([0x40 if qos == 1 else 0x50, 2]) + mid)
                    self.messages.append(Message(topic, rest, qos, retain))
                elif kind == 6:  # PUBREL (QoS 2)
                    writer.write(bytes([0x70, 2]) + body[:2])
                elif kind == 12:  # PINGREQ
                    writer.write(bytes([0xD0, 0]))
                elif kind == 14:  # DISCONNECT
                    return
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    def _connect(self, body: bytes) -> bool:
        flags = body[7]
        pos = 10
        fields = []
        while pos < len(body):
            size = int.from_bytes(body[pos : pos + 2], "big")
            fields.append(body[pos + 2 : pos + 2 + size].decode())
            pos += 2 + size
        client_id, rest = fields[0], fields[1:]
        self.client_ids.append(client_id)
        if self.users is None:
            return True
        user = rest[0] if flags & 0x80 else None
        password = rest[1] if flags & 0x40 else None
        return user is not None and self.users.get(user) == password


async def _read_length(reader: asyncio.StreamReader) -> int:
    value, shift = 0, 0
    while True:
        byte = (await reader.readexactly(1))[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
        shift += 7
