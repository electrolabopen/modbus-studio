"""Audit log of every write sent to a device.

Each entry is one JSON line, appended and flushed to disk before the next write
can be logged, so the record survives a crash or a container restart. The file
rotates once to ``<name>.1`` when it grows past ``max_bytes``. The most recent
entries are also kept in memory for the API and the UI.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from ..models.views import WriteLogEntry

log = logging.getLogger(__name__)

Listener = Callable[[WriteLogEntry], None]


class WriteLog:
    def __init__(
        self, path: Path | None = None, keep: int = 500, max_bytes: int = 5_000_000
    ) -> None:
        self.path = path
        self._max_bytes = max_bytes
        self._entries: deque[WriteLogEntry] = deque(maxlen=keep)
        self._listeners: list[Listener] = []
        self._seq = 0
        if path is not None:
            self._load(path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            log.error("could not read write log %s: %s", path, exc)
            return
        for line in lines[-(self._entries.maxlen or 0) :]:
            try:
                self._entries.append(WriteLogEntry.model_validate_json(line))
            except ValueError:
                continue  # a line cut by a crash; the rest is still useful
        if self._entries:
            self._seq = self._entries[-1].seq

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def record(self, **fields: object) -> WriteLogEntry:
        self._seq += 1
        entry = WriteLogEntry.model_validate({"seq": self._seq, "timestamp": time.time(), **fields})
        self._entries.append(entry)
        if self.path is not None:
            try:
                self._append(self.path, entry)
            except OSError as exc:
                # The write already happened on the device; failing it now would mislead.
                log.error("could not append to write log %s: %s", self.path, exc)
        for listener in list(self._listeners):
            listener(entry)
        return entry

    def _append(self, path: Path, entry: WriteLogEntry) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > self._max_bytes:
            path.replace(path.with_name(path.name + ".1"))
        line = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n"
        if self._ends_mid_line(path):
            line = "\n" + line  # do not glue this entry to a line cut by a crash
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def _ends_mid_line(path: Path) -> bool:
        if not path.exists() or path.stat().st_size == 0:
            return False
        with path.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            return f.read(1) != b"\n"

    def entries(self, limit: int | None = None) -> list[WriteLogEntry]:
        """Newest first."""
        items = list(reversed(self._entries))
        return items if limit is None else items[:limit]
