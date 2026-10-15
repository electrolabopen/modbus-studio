"""Modbus RTU over a real serial line: the simulator on one end of a pair of connected ports.

On Linux the pair is made with socat (two ptys); elsewhere set
MODBUS_STUDIO_TEST_SERIAL_PAIR, e.g. to a com0com pair "COM10,COM11".
"""

import asyncio
import sys

import pytest

from modbus_studio.core.codec import ByteOrder, DataType, decode
from modbus_studio.core.connection import ConnectionManager, ErrorKind, RequestError
from modbus_studio.core.poller import PollManager, PollResult
from modbus_studio.core.traffic import Direction, TrafficLog
from modbus_studio.models import PollDefinition, ReadFunction, RtuConnection
from modbus_studio.simulator import CONST_INT32, CONST_UINT32, SerialLine, Simulator

from .test_connection import crc16_modbus

HR = ReadFunction.READ_HOLDING_REGISTERS


@pytest.fixture
async def line(manager: ConnectionManager, serial_simulator: str):
    return manager.add(
        RtuConnection(id="line", serial_port=serial_simulator, parity="N", timeout_s=0.5)
    )


async def test_read_typed_values(line):
    regs = await line.read(HR, device_id=1, address=0, count=28)
    assert decode(regs[24:26], DataType.INT32) == CONST_INT32
    assert decode(regs[26:28], DataType.UINT32, ByteOrder.CDAB) == CONST_UINT32
    assert len(await line.read(ReadFunction.READ_COILS, 2, 0, 10)) == 10
    bits = await line.read(ReadFunction.READ_DISCRETE_INPUTS, 1, 0, 16)
    assert sum(bits) == 1


async def test_writes(line):
    await line.write_register(1, 100, 0xBEEF)
    await line.write_registers(1, 101, [1, 2, 3])
    assert await line.read(HR, 1, 100, 4) == [0xBEEF, 1, 2, 3]
    await line.write_coils(1, 10, [True, False, True])
    coils = await line.read(ReadFunction.READ_COILS, 1, 0, 16)
    assert [i for i, c in enumerate(coils) if c] == [10, 12]


async def test_exception_response(line):
    with pytest.raises(RequestError) as info:
        await line.read(HR, 1, 199, 5)
    assert info.value.kind is ErrorKind.EXCEPTION and info.value.exception_code == 2


async def test_frames_are_rtu_with_crc(line, traffic: TrafficLog):
    await line.read(HR, 1, 24, 2)
    tx, rx = traffic.entries("line")
    assert tx.direction is Direction.TX and rx.direction is Direction.RX
    assert tx.data == bytes([1, 3, 0, 24, 0, 2]) + crc16_modbus(bytes([1, 3, 0, 24, 0, 2]))
    assert rx.data[:3] == bytes([1, 3, 4]) and rx.data[-2:] == crc16_modbus(rx.data[:-2])


async def test_cancelled_request_does_not_shift_later_replies(line, traffic: TrafficLog):
    """RTU has no transaction id: a reply that arrives after its request was cancelled
    (a window stopped mid-request) must not be taken as the reply to the next one."""
    sent = asyncio.Event()
    traffic.subscribe(lambda e: e.direction is Direction.TX and sent.set())
    for _ in range(5):
        sent.clear()
        pending = asyncio.create_task(line.read(HR, 1, 24, 2))
        await sent.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        regs = await line.read(HR, 1, 26, 2)
        assert decode(regs, DataType.UINT32, ByteOrder.CDAB) == CONST_UINT32


async def test_simulator_reports_a_missing_serial_port():
    port = "COM250" if sys.platform == "win32" else "/dev/ttyMODBUS-STUDIO-TEST"
    sim = Simulator(tcp_port=0, rtu_tcp_port=0, serial=SerialLine(port))
    with pytest.raises(RuntimeError, match=f"failed to start RTU on {port}.*not found"):
        await sim.start()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux pseudo-terminals")
async def test_parity_refused_by_a_pty_is_explained(manager, serial_pair):
    conn = manager.add(RtuConnection(id="pty", serial_port=serial_pair[1], parity="E"))
    assert not await conn.connect()
    assert "does not accept these line settings" in conn.last_error


async def test_windows_poll_a_shared_serial_line(manager, line):
    """Two windows at different scan rates share one RTU line, and one is removed
    while the other keeps polling."""
    polls = PollManager(manager)
    results: list[PollResult] = []
    polls.subscribe(results.append)
    polls.add(
        PollDefinition(id="int32", connection_id="line", address=24, quantity=2, scan_rate_ms=10)
    )
    polls.add(
        PollDefinition(id="uint32", connection_id="line", address=26, quantity=2, scan_rate_ms=15)
    )
    await asyncio.sleep(0.3)
    await polls.remove("int32")
    await asyncio.sleep(0.2)
    await polls.stop_all()

    assert all(r.ok for r in results), [r.error for r in results if not r.ok]
    int32 = [r for r in results if r.poll_id == "int32"]
    uint32 = [r for r in results if r.poll_id == "uint32"]
    assert len(int32) >= 5 and len(uint32) >= 10
    assert {decode(r.values, DataType.INT32) for r in int32} == {CONST_INT32}
    assert {decode(r.values, DataType.UINT32, ByteOrder.CDAB) for r in uint32} == {CONST_UINT32}
