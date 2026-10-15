import asyncio
import os

import pytest

from modbus_studio.core.codec import ByteOrder, DataType, decode
from modbus_studio.core.connection import ConnectionManager, ErrorKind, RequestError
from modbus_studio.core.traffic import Direction, TrafficLog
from modbus_studio.models import ReadFunction, RtuConnection, TcpConnection
from modbus_studio.simulator import CONST_INT32, CONST_UINT32

HR = ReadFunction.READ_HOLDING_REGISTERS


def crc16_modbus(data: bytes) -> bytes:
    """Reference CRC from the Modbus serial line specification, appended low byte first."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


async def test_read_typed_values(any_conn):
    conn = any_conn
    regs = await conn.read(HR, device_id=1, address=0, count=28)
    assert len(regs) == 28
    assert decode(regs[24:26], DataType.INT32) == CONST_INT32
    assert decode(regs[26:28], DataType.UINT32, ByteOrder.CDAB) == CONST_UINT32
    # The four float32 copies hold the same value in different byte orders.
    floats = [
        decode(regs[10:12], DataType.FLOAT32, ByteOrder.ABCD),
        decode(regs[12:14], DataType.FLOAT32, ByteOrder.CDAB),
        decode(regs[14:16], DataType.FLOAT32, ByteOrder.BADC),
        decode(regs[16:18], DataType.FLOAT32, ByteOrder.DCBA),
    ]
    assert len(set(floats)) == 1
    assert -100.0 <= floats[0] <= 100.0


async def test_all_read_functions(tcp):
    assert len(await tcp.read(ReadFunction.READ_COILS, 1, 0, 10)) == 10
    bits = await tcp.read(ReadFunction.READ_DISCRETE_INPUTS, 1, 0, 16)
    assert len(bits) == 16 and sum(bits) == 1  # one walking bit
    assert len(await tcp.read(ReadFunction.READ_INPUT_REGISTERS, 1, 0, 3)) == 3


async def test_bit_read_is_trimmed_to_quantity(tcp):
    assert len(await tcp.read(ReadFunction.READ_COILS, 1, 0, 3)) == 3


async def test_writes(any_conn):
    conn = any_conn
    await conn.write_register(1, 100, 0xBEEF)  # FC06
    await conn.write_registers(1, 101, [1, 2, 3])  # FC16
    assert await conn.read(HR, 1, 100, 4) == [0xBEEF, 1, 2, 3]
    await conn.write_coil(1, 5, True)  # FC05
    await conn.write_coils(1, 10, [True, False, True])  # FC15
    coils = await conn.read(ReadFunction.READ_COILS, 1, 0, 16)
    assert [i for i, c in enumerate(coils) if c] == [5, 10, 12]


async def test_devices_are_independent(tcp):
    await tcp.write_register(1, 150, 11)
    await tcp.write_register(2, 150, 22)
    assert await tcp.read(HR, 1, 150, 1) == [11]
    assert await tcp.read(HR, 2, 150, 1) == [22]


async def test_exception_response(tcp):
    with pytest.raises(RequestError) as info:
        await tcp.read(HR, 1, 199, 5)  # runs past the end of the map
    assert info.value.kind is ErrorKind.EXCEPTION
    assert info.value.exception_code == 2
    assert "Illegal data address" in str(info.value)
    assert tcp.stats.exceptions == 1 and tcp.stats.requests == 1


async def test_unknown_device_id(tcp):
    with pytest.raises(RequestError) as info:
        await tcp.read(HR, 9, 0, 1)
    assert info.value.kind is ErrorKind.EXCEPTION


async def test_timeout(manager, silent_port):
    conn = manager.add(
        TcpConnection(id="silent", host="127.0.0.1", port=silent_port, timeout_s=0.2)
    )
    with pytest.raises(RequestError) as info:
        await conn.read(HR, 1, 0, 1)
    assert info.value.kind is ErrorKind.TIMEOUT
    assert conn.stats.timeouts == 1
    # The connection survives a timeout and the next request is attempted normally.
    with pytest.raises(RequestError):
        await conn.read(HR, 1, 0, 1)
    assert conn.stats.timeouts == 2


async def test_connection_refused(manager):
    from tests.integration.conftest import free_port

    conn = manager.add(
        TcpConnection(id="nobody", host="127.0.0.1", port=free_port(), timeout_s=0.2)
    )
    with pytest.raises(RequestError) as info:
        await conn.read(HR, 1, 0, 1)
    assert info.value.kind is ErrorKind.DISCONNECTED
    assert conn.stats.disconnected == 1 and conn.stats.requests == 0
    assert str(info.value).startswith("cannot connect to 127.0.0.1:")
    assert conn.last_error == str(info.value)


async def test_unknown_host_is_reported(manager):
    # .invalid is reserved by RFC 6761 and never resolves.
    conn = manager.add(TcpConnection(id="typo", host="modbus-sim.invalid", port=5020))
    with pytest.raises(RequestError) as info:
        await conn.read(HR, 1, 0, 1)
    assert info.value.kind is ErrorKind.DISCONNECTED
    assert str(info.value) == "cannot resolve host 'modbus-sim.invalid'"
    assert conn.last_error == str(info.value)


async def test_missing_serial_port_is_reported(manager):
    port = "COM250" if os.name == "nt" else "/dev/ttyMODBUS-STUDIO-TEST"
    conn = manager.add(RtuConnection(id="rtu", serial_port=port, timeout_s=0.2))
    with pytest.raises(RequestError) as info:
        await conn.read(HR, 1, 0, 1)
    assert info.value.kind is ErrorKind.DISCONNECTED
    assert str(info.value).startswith(f"serial port {port} not found")
    assert conn.last_error == str(info.value)


async def test_last_error_cleared_on_connect(tcp):
    tcp.last_error = "stale"
    await tcp.read(HR, 1, 0, 1)
    assert tcp.last_error is None


async def test_tcp_traffic_capture(tcp, traffic: TrafficLog):
    await tcp.read(HR, 1, 0, 2)
    tx, rx = traffic.entries("tcp")
    assert tx.direction is Direction.TX and rx.direction is Direction.RX
    # MBAP: transaction id, protocol 0, length 6, unit 1 | PDU: 03 0000 0002
    assert tx.data[2:] == bytes.fromhex("0000 0006 01 03 0000 0002")
    assert tx.data[:2] == rx.data[:2]  # matching transaction id
    assert rx.data[7:9] == bytes.fromhex("03 04")
    assert tx.hex.startswith(tx.data[:1].hex().upper())


async def test_rtu_traffic_capture_has_valid_crc(rtu_tcp, traffic: TrafficLog):
    await rtu_tcp.read(HR, 1, 5, 2)
    tx, rx = traffic.entries("rtu")
    body = bytes.fromhex("01 03 0005 0002")
    assert tx.data == body + crc16_modbus(body)
    assert rx.data[:3] == bytes.fromhex("01 03 04")
    assert rx.data[-2:] == crc16_modbus(rx.data[:-2])


async def test_manager_rejects_duplicates(manager: ConnectionManager):
    manager.add(TcpConnection(id="x", host="127.0.0.1"))
    with pytest.raises(ValueError):
        manager.add(TcpConnection(id="x", host="127.0.0.1"))
    with pytest.raises(KeyError):
        manager.get("missing")


async def test_cancelled_request_does_not_answer_the_next_one(any_conn, traffic: TrafficLog):
    """A request cancelled after it was sent still gets its reply; the next request
    must not take it as its own (RTU frames have no transaction id)."""
    sent = asyncio.Event()
    traffic.subscribe(lambda e: e.direction is Direction.TX and sent.set())
    for _ in range(5):
        sent.clear()
        pending = asyncio.create_task(any_conn.read(HR, 1, 24, 2))
        await sent.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        regs = await any_conn.read(HR, 1, 26, 2)
        assert decode(regs, DataType.UINT32, ByteOrder.CDAB) == CONST_UINT32
    assert any_conn.stats.timeouts == 0
