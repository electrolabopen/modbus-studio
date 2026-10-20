"""Polled values reach an MQTT broker, and the broker never slows down polling."""

import asyncio
import json
import socket

from modbus_studio.core.connection import Connection
from modbus_studio.core.poller import ErrorKind, PollResult
from modbus_studio.core.studio import Studio
from modbus_studio.models import PollDefinition, TcpConnection
from modbus_studio.models.exporters import MQTTConfig
from modbus_studio.models.format import RegisterFormatModel

from ..mqtt_broker import FakeBroker


def window(**overrides) -> PollDefinition:
    values = {
        "id": "w",
        "name": "Simulator",
        "connection_id": "sim",
        "address": 0,
        "quantity": 4,
        "scan_rate_ms": 50,
        "formats": {
            0: RegisterFormatModel(dtype="uint16", alias="counter"),
            2: RegisterFormatModel(scale=0.1, unit="°C", alias="temperature"),
        },
    }
    return PollDefinition(**{**values, **overrides})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def until(condition, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.02)


async def test_polled_values_are_published(simulator):
    broker = await FakeBroker().start()
    studio = Studio()
    try:
        studio.add_connection(
            TcpConnection(id="sim", name="Sim", host="127.0.0.1", port=simulator.tcp)
        )
        studio.set_mqtt(MQTTConfig(enabled=True, host="127.0.0.1", port=broker.port))
        studio.add_poll(window())
        messages = await broker.wait_for(8)
        await until(lambda: studio.mqtt.status.points_sent >= 8)
        status = studio.mqtt.status.model_copy()
    finally:
        await studio.close()
        await broker.stop()

    assert status.connected is True and status.state == "ok"
    first = {m.topic: json.loads(m.payload) for m in messages[:4]}
    assert set(first) == {
        "modbus-studio/Sim/1/counter",
        "modbus-studio/Sim/1/1",
        "modbus-studio/Sim/1/temperature",
        "modbus-studio/Sim/1/3",
    }
    temperature = first["modbus-studio/Sim/1/temperature"]
    assert temperature["unit"] == "°C" and temperature["alias"] == "temperature"
    assert -50.0 <= temperature["value"] <= 150.0  # scaled, not the raw x10 register
    assert temperature["timestamp"].endswith("Z")
    assert all(m.qos == 0 and not m.retain for m in messages)
    assert broker.client_ids[0].startswith("modbus-studio-")


async def test_qos_retain_topic_and_aliased_only(simulator):
    broker = await FakeBroker().start()
    studio = Studio()
    config = MQTTConfig(
        enabled=True, host="127.0.0.1", port=broker.port, qos=2, retain=True,
        topic="plant/{window}/{alias}", aliased_only=True, client_id="tester",
    )  # fmt: skip
    try:
        studio.add_connection(TcpConnection(id="sim", host="127.0.0.1", port=simulator.tcp))
        studio.set_mqtt(config)
        studio.add_poll(window())
        messages = await broker.wait_for(4)
        await until(lambda: studio.mqtt.status.points_sent >= 4)  # QoS 2 completed
    finally:
        await studio.close()
        await broker.stop()

    assert {m.topic for m in messages} == {"plant/Simulator/counter", "plant/Simulator/temperature"}
    assert all(m.qos == 2 and m.retain for m in messages)
    assert broker.client_ids == ["tester"]


async def test_wrong_credentials_are_reported():
    broker = await FakeBroker(users={"modbus": "right"}).start()
    studio = Studio()
    try:
        config = MQTTConfig(
            enabled=True, host="127.0.0.1", port=broker.port, username="modbus", password="wrong"
        )
        studio.set_mqtt(config)
        await until(lambda: studio.mqtt.status.state == "error")
        status = studio.mqtt.status
        assert status.connected is False
        assert "connection refused by the broker" in status.last_error

        # Fixing the password (the rest of the settings unchanged) connects.
        studio.set_mqtt(studio.mqtt.config.model_copy(update={"password": "right"}))
        await until(lambda: studio.mqtt.status.connected)
        assert studio.mqtt.status.state == "ok"
    finally:
        await studio.close()
        await broker.stop()


async def test_a_missing_broker_does_not_slow_polling_and_buffers(simulator):
    port = free_port()
    studio = Studio()
    try:
        studio.add_connection(TcpConnection(id="sim", host="127.0.0.1", port=simulator.tcp))
        studio.set_mqtt(MQTTConfig(enabled=True, host="127.0.0.1", port=port, qos=1))
        task = studio.add_poll(window(scan_rate_ms=20))
        # Windows takes about 2 s to report a refused connection to localhost.
        await until(lambda: studio.mqtt.status.state == "error")
        started = studio.polls.get(task.definition.id).stats.valid
        await asyncio.sleep(1.0)
        status = studio.mqtt.status
        assert status.connected is False
        assert "connection refused" in status.last_error
        # Still polling every ~20 ms while the broker is unreachable.
        assert studio.polls.get(task.definition.id).stats.valid - started >= 20
        buffered = status.pending
        assert buffered >= 80

        # The broker comes up: the buffered values are delivered, oldest first.
        broker = await FakeBroker().start(port)
        try:
            await broker.wait_for(buffered, timeout=20)
            await until(lambda: studio.mqtt.status.state == "ok")
            stamps = [json.loads(m.payload)["timestamp"] for m in broker.messages[:buffered]]
            assert stamps == sorted(stamps)
        finally:
            await studio.close()
            await broker.stop()
    finally:
        await studio.close()


async def test_disabling_disconnects():
    broker = await FakeBroker().start()
    studio = Studio()
    try:
        config = MQTTConfig(enabled=True, host="127.0.0.1", port=broker.port)
        studio.set_mqtt(config)
        await until(lambda: studio.mqtt.status.connected)
        studio.set_mqtt(config.model_copy(update={"enabled": False}))
        assert studio.mqtt.status.state == "disabled"
        assert studio.mqtt.status.connected is False
        await until(lambda: not broker._writers)
    finally:
        await studio.close()
        await broker.stop()


async def test_a_connection_closed_without_an_answer_is_explained():
    broker = await FakeBroker(hang_up=True).start()
    studio = Studio()
    try:
        studio.set_mqtt(MQTTConfig(enabled=True, host="127.0.0.1", port=broker.port))
        await until(lambda: studio.mqtt.status.state == "error")
        assert "check the port and the TLS setting" in studio.mqtt.status.last_error
    finally:
        await studio.close()
        await broker.stop()


async def test_a_missing_tls_file_is_named():
    studio = Studio()
    try:
        studio.set_mqtt(
            MQTTConfig(enabled=True, host="127.0.0.1", tls=True, ca_file="/nowhere/ca.pem")
        )
        status = studio.mqtt.status
        assert status.state == "error" and status.connected is False
        assert "ca_file '/nowhere/ca.pem' not found" in status.last_error
    finally:
        await studio.close()


async def test_issue_1_on_change_publishes_both_edges_of_a_100_ms_pulse(simulator, tcp: Connection):
    """Issue #1: a door bit high for 100 ms, polled every 50 ms, gives exactly two
    messages, the rising and the falling edge, after the state at start-up."""
    broker = await FakeBroker().start()
    studio = Studio()
    config = MQTTConfig(enabled=True, host="127.0.0.1", port=broker.port, publish_mode="on_change")
    door = PollDefinition(
        id="door", name="Door", connection_id="sim", function=1, address=0, quantity=1,
        scan_rate_ms=50, formats={0: RegisterFormatModel(alias="door")},
    )  # fmt: skip
    try:
        await tcp.write_coil(1, 0, False)  # tcp: the machine, on a connection of its own
        studio.add_connection(
            TcpConnection(id="sim", name="Sim", host="127.0.0.1", port=simulator.tcp)
        )
        studio.set_mqtt(config)
        studio.add_poll(door)
        await broker.wait_for(1)  # the state at start-up
        polls = studio.polls.get("door").stats

        await asyncio.sleep(0.5)  # the door stays closed
        before = polls.valid
        await tcp.write_coil(1, 0, True)
        await asyncio.sleep(0.1)
        await tcp.write_coil(1, 0, False)
        await asyncio.sleep(0.5)
        assert polls.valid - before >= 10  # still polling every ~50 ms
        await until(lambda: studio.mqtt.status.pending == 0)
        unchanged = studio.mqtt.status.unchanged
    finally:
        await studio.close()
        await broker.stop()

    values = [json.loads(m.payload)["value"] for m in broker.messages]
    assert values == [False, True, False]
    assert {m.topic for m in broker.messages} == {"modbus-studio/Sim/1/door"}
    assert unchanged >= 15


async def test_on_change_republishes_after_failed_reads_and_per_register_deadbands():
    broker = await FakeBroker().start()
    studio = Studio()
    config = MQTTConfig(
        enabled=True, host="127.0.0.1", port=broker.port, publish_mode="on_change",
        deadband=5,
    )  # fmt: skip
    # Never polled (nothing listens on its port): results are handed in by the test.
    studio.add_connection(TcpConnection(id="sim", name="Sim", host="127.0.0.1", port=free_port()))
    studio.add_poll(
        window(
            enabled=False,
            quantity=4,
            formats={
                0: RegisterFormatModel(alias="a"),
                1: RegisterFormatModel(alias="b", deadband=0),
                2: RegisterFormatModel(alias="c", dtype="float32"),
            },
        )
    )
    seq = 0

    def poll(values: list[int] | None) -> None:
        nonlocal seq
        seq += 1
        studio._export(
            PollResult(
                poll_id="w", seq=seq, timestamp=1000.0 + seq, duration_ms=1.0, values=values,
                error_kind=ErrorKind.TIMEOUT if values is None else None,
            )
        )  # fmt: skip

    def sent() -> list[tuple[str, object]]:
        return [
            (m.topic.rsplit("/", 1)[1], json.loads(m.payload)["value"]) for m in broker.messages
        ]

    try:
        studio.set_mqtt(config)
        await until(lambda: studio.mqtt.status.connected)
        poll([100, 100, 0, 0])
        poll([103, 101, 0, 0])  # a: within the exporter's deadband; b: its own is 0
        poll(None)  # timeout
        poll([103, 101, 0, 0])  # the same values again, but after a failed read
        poll([103, 101, 0x7FC0, 0])  # c: NaN, which JSON cannot carry
        poll([103, 101, 0, 0])
        await broker.wait_for(8)
    finally:
        await studio.close()
        await broker.stop()

    assert sent() == [
        ("a", 100), ("b", 100), ("c", 0.0),
        ("b", 101),
        ("a", 103), ("b", 101), ("c", 0.0),
        ("c", 0.0),
    ]  # fmt: skip
