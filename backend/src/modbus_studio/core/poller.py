"""Periodic reads for each polling window."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from ..models.poll import PollDefinition
from .connection import Connection, ConnectionManager, ErrorKind, RequestError

log = logging.getLogger(__name__)

# While the connection is down, retry no faster than this.
RECONNECT_INTERVAL_S = 1.0


@dataclass
class PollStats:
    polls: int = 0
    valid: int = 0
    timeouts: int = 0
    exceptions: int = 0
    invalid: int = 0
    disconnected: int = 0

    @property
    def errors(self) -> int:
        return self.timeouts + self.exceptions + self.invalid + self.disconnected

    def count(self, kind: ErrorKind) -> None:
        if kind is ErrorKind.TIMEOUT:
            self.timeouts += 1
        elif kind is ErrorKind.EXCEPTION:
            self.exceptions += 1
        elif kind is ErrorKind.INVALID:
            self.invalid += 1
        else:
            self.disconnected += 1

    def as_dict(self) -> dict[str, int]:
        return {**asdict(self), "errors": self.errors}


@dataclass(frozen=True)
class PollResult:
    poll_id: str
    seq: int
    timestamp: float
    duration_ms: float
    values: list[int] | list[bool] | None
    error_kind: ErrorKind | None = None
    error: str | None = None
    exception_code: int | None = None
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error_kind is None


ResultListener = Callable[[PollResult], None]


class PollTask:
    def __init__(
        self, definition: PollDefinition, connection: Connection, on_result: ResultListener
    ) -> None:
        self.definition = definition
        self.connection = connection
        self.stats = PollStats()
        self.last_result: PollResult | None = None
        self._on_result = on_result
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def poll_once(self) -> PollResult:
        d = self.definition
        self.stats.polls += 1
        started = time.monotonic()
        values: list[int] | list[bool] | None = None
        error: RequestError | None = None
        try:
            values = await self.connection.read(d.function, d.device_id, d.address, d.quantity)
            self.stats.valid += 1
        except RequestError as exc:
            error = exc
            self.stats.count(exc.kind)
        result = PollResult(
            poll_id=d.id,
            seq=self.stats.polls,
            timestamp=time.time(),
            duration_ms=(time.monotonic() - started) * 1000,
            values=values,
            error_kind=error.kind if error else None,
            error=str(error) if error else None,
            exception_code=error.exception_code if error else None,
            stats=self.stats.as_dict(),
        )
        self.last_result = result
        try:
            self._on_result(result)
        except Exception:
            log.exception("poll result listener failed")
        return result

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        # The flag, not just cancellation, ends the loop: see stop().
        while not self._stopping:
            result = await self.poll_once()
            interval = self.definition.scan_rate_ms / 1000
            if result.error_kind is ErrorKind.DISCONNECTED:
                interval = max(interval, RECONNECT_INTERVAL_S)
            next_at += interval
            now = loop.time()
            if next_at < now:  # the device is slower than the scan rate: don't burst
                next_at = now
            await asyncio.sleep(next_at - now)

    def start(self) -> None:
        if not self.running:
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name=f"poll:{self.definition.id}")

    def cancel(self) -> None:
        """Request cancellation without waiting; ``stop()`` waits for it."""
        self._stopping = True
        if self._task is not None:
            self._task.cancel()

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stopping = True
        # Before Python 3.12, asyncio.wait_for (pymodbus awaits every response with
        # it) can swallow a cancellation that races with the response, and the loop
        # would carry on. Keep cancelling until the task has really finished.
        while not task.done():
            task.cancel()
            await asyncio.wait({task}, timeout=0.1)
        with contextlib.suppress(asyncio.CancelledError):
            task.result()
        self._task = None

    def reset_stats(self) -> None:
        self.stats = PollStats()


class PollManager:
    def __init__(self, connections: ConnectionManager) -> None:
        self._connections = connections
        self._tasks: dict[str, PollTask] = {}
        self._listeners: list[ResultListener] = []

    def subscribe(self, listener: ResultListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def _dispatch(self, result: PollResult) -> None:
        for listener in list(self._listeners):
            try:
                listener(result)
            except Exception:
                log.exception("poll listener failed")

    def add(self, definition: PollDefinition) -> PollTask:
        if definition.id in self._tasks:
            raise ValueError(f"poll {definition.id!r} already exists")
        task = PollTask(definition, self._connections.get(definition.connection_id), self._dispatch)
        self._tasks[definition.id] = task
        if definition.enabled:
            task.start()
        return task

    async def update(self, definition: PollDefinition) -> PollTask:
        """Replace a window's definition.

        Display-only changes (name, formats) are applied in place, keeping the
        task and its counters. Anything that changes the request restarts it.
        """
        current = self._tasks.get(definition.id)
        if current is not None and current.definition.polling_key() == definition.polling_key():
            current.definition = definition
            return current
        await self.remove(definition.id)
        return self.add(definition)

    def using_connection(self, connection_id: str) -> list[PollTask]:
        return [t for t in self._tasks.values() if t.definition.connection_id == connection_id]

    def get(self, poll_id: str) -> PollTask:
        try:
            return self._tasks[poll_id]
        except KeyError:
            raise KeyError(f"unknown poll {poll_id!r}") from None

    def all(self) -> list[PollTask]:
        return list(self._tasks.values())

    async def remove(self, poll_id: str) -> None:
        task = self._tasks.pop(poll_id, None)
        if task is not None:
            await task.stop()

    async def stop_all(self) -> None:
        tasks = list(self._tasks.values())
        # Cancel every window before awaiting any: otherwise, while the first one unwinds,
        # another can take the connection lock and send one more request.
        for task in tasks:
            task.cancel()
        for task in tasks:
            await task.stop()
        self._tasks.clear()
