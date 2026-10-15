import asyncio

from modbus_studio.core.connection import ErrorKind
from modbus_studio.core.poller import PollManager, PollResult
from modbus_studio.models import PollDefinition, ReadFunction, TcpConnection


async def test_poll_once(manager, tcp):
    polls = PollManager(manager)
    task = polls.add(
        PollDefinition(id="w1", connection_id="tcp", address=24, quantity=4, enabled=False)
    )
    result = await task.poll_once()
    assert result.ok and result.seq == 1 and len(result.values) == 4
    assert result.stats["valid"] == 1 and result.stats["errors"] == 0
    assert task.last_result is result


async def test_windows_share_a_connection(manager, tcp, traffic):
    polls = PollManager(manager)
    results: list[PollResult] = []
    polls.subscribe(results.append)
    polls.add(PollDefinition(id="regs", connection_id="tcp", quantity=20, scan_rate_ms=20))
    polls.add(
        PollDefinition(
            id="coils",
            connection_id="tcp",
            function=ReadFunction.READ_COILS,
            quantity=50,
            scan_rate_ms=30,
        )
    )
    await asyncio.sleep(0.5)
    await polls.stop_all()

    by_window = {pid: [r for r in results if r.poll_id == pid] for pid in ("regs", "coils")}
    assert all(r.ok for r in results), [r.error for r in results if not r.ok]
    assert len(by_window["regs"]) >= 5 and len(by_window["coils"]) >= 5
    # Different scan rates give different poll counts.
    assert len(by_window["regs"]) > len(by_window["coils"])
    # Requests were serialised: frames strictly alternate TX, RX on the shared socket.
    # stop_all() may cancel one request in flight, leaving a final unanswered TX.
    directions = [e.direction.value for e in traffic.entries("tcp")]
    pairs = len(directions) // 2
    assert directions[: pairs * 2] == ["tx", "rx"] * pairs
    assert directions[pairs * 2 :] in ([], ["tx"])


async def test_errors_are_counted_per_window(manager, tcp):
    polls = PollManager(manager)
    task = polls.add(
        PollDefinition(id="bad", connection_id="tcp", address=195, quantity=10, enabled=False)
    )
    for _ in range(3):
        result = await task.poll_once()
    assert result.error_kind is ErrorKind.EXCEPTION and result.exception_code == 2
    assert result.values is None
    assert result.stats == {
        "polls": 3,
        "valid": 0,
        "timeouts": 0,
        "exceptions": 3,
        "invalid": 0,
        "disconnected": 0,
        "errors": 3,
    }


async def test_disconnected_window_keeps_running(manager):
    from tests.integration.conftest import free_port

    manager.add(TcpConnection(id="down", host="127.0.0.1", port=free_port(), timeout_s=0.1))
    polls = PollManager(manager)
    task = polls.add(PollDefinition(id="w", connection_id="down", scan_rate_ms=10))
    await asyncio.sleep(0.3)
    assert task.running
    # Reconnection attempts are throttled, not done at the 10 ms scan rate.
    assert 1 <= task.stats.disconnected <= 2
    await polls.stop_all()
    assert not task.running


async def test_update_restarts_with_new_definition(manager, tcp):
    polls = PollManager(manager)
    polls.add(PollDefinition(id="w", connection_id="tcp", quantity=2, enabled=False))
    task = await polls.update(
        PollDefinition(id="w", connection_id="tcp", quantity=5, enabled=False)
    )
    assert len((await task.poll_once()).values) == 5
    assert polls.get("w") is task


async def test_stop_survives_a_swallowed_cancellation(manager, tcp):
    """On Python < 3.12 asyncio.wait_for (used by pymodbus for every response) can
    swallow a cancellation that races with the response. Stopping must still work."""
    swallowed: list[bool] = []

    async def read(*args: object, **kwargs: object) -> list[int]:
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            swallowed.append(True)  # what wait_for does when the response wins the race
        return [0]

    tcp.read = read
    polls = PollManager(manager)
    polls.add(PollDefinition(id="s", connection_id="tcp", quantity=1, scan_rate_ms=10))
    await asyncio.sleep(0.05)
    await asyncio.wait_for(polls.stop_all(), timeout=2)
    assert swallowed
