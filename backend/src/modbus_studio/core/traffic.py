"""Capture of raw Modbus frames (TX/RX) for the traffic monitor."""

from __future__ import annotations

import itertools
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class Direction(str, Enum):
    TX = "tx"
    RX = "rx"


@dataclass(frozen=True)
class TrafficEntry:
    seq: int
    timestamp: float
    connection_id: str
    direction: Direction
    data: bytes

    @property
    def hex(self) -> str:
        return self.data.hex(" ").upper()


TrafficListener = Callable[[TrafficEntry], None]


class TrafficLog:
    """Bounded in-memory log of frames shared by all connections."""

    def __init__(self, maxlen: int = 5000) -> None:
        self._entries: deque[TrafficEntry] = deque(maxlen=maxlen)
        self._seq = itertools.count(1)
        self._listeners: list[TrafficListener] = []

    def record(self, connection_id: str, direction: Direction, data: bytes) -> TrafficEntry:
        entry = TrafficEntry(next(self._seq), time.time(), connection_id, direction, bytes(data))
        self._entries.append(entry)
        for listener in list(self._listeners):
            try:
                listener(entry)
            except Exception:  # a broken listener must never break polling
                log.exception("traffic listener failed")
        return entry

    def entries(self, connection_id: str | None = None, after_seq: int = 0) -> list[TrafficEntry]:
        return [
            e
            for e in self._entries
            if e.seq > after_seq and (connection_id is None or e.connection_id == connection_id)
        ]

    def clear(self) -> None:
        self._entries.clear()

    def subscribe(self, listener: TrafficListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe
