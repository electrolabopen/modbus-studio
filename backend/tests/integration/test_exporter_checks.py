"""The "test connection" of the exporters: tries settings without saving them."""

import httpx

from modbus_studio.core.studio import Studio
from modbus_studio.models.exporters import InfluxDBConfig, MQTTConfig

from ..mqtt_broker import FakeBroker
from .conftest import free_port

INFLUX = InfluxDBConfig(url="http://influx:8086", org="plant", bucket="modbus", token="t")


def influx_studio(handler) -> Studio:
    return Studio(influx_transport=httpx.MockTransport(handler))


async def test_influxdb_accepts_an_empty_write():
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204, headers={"X-Influxdb-Version": "v2.7.11"})

    result = await influx_studio(handle).test_influxdb(INFLUX)
    assert result.ok, result
    assert "InfluxDB v2.7.11" in result.message and "'modbus'" in result.message
    (request,) = seen
    assert request.content == b""  # nothing is stored
    assert request.url.params["org"] == "plant" and request.url.params["bucket"] == "modbus"
    assert request.headers["Authorization"] == "Token t"


async def test_influxdb_errors_are_explained():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "unauthorized", "message": "unauthorized access"})

    result = await influx_studio(handle).test_influxdb(INFLUX)
    assert not result.ok and result.message.startswith("unauthorized: check the token")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = await influx_studio(refuse).test_influxdb(INFLUX)
    assert not result.ok and "cannot connect to http://influx:8086" in result.message

    result = await influx_studio(refuse).test_influxdb(INFLUX.model_copy(update={"token": ""}))
    assert not result.ok and result.message == "missing: token"


async def test_influxdb_test_uses_the_saved_token_and_saves_nothing():
    tokens: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        tokens.append(request.headers["Authorization"])
        return httpx.Response(204)

    studio = influx_studio(handle)
    try:
        studio.set_influxdb(INFLUX.model_copy(update={"token": "saved"}))
        result = await studio.test_influxdb(INFLUX.model_copy(update={"token": None, "org": "o2"}))
        assert result.ok
        assert "Token saved" in tokens
        assert studio.influx.config.org == "plant"  # not applied
    finally:
        await studio.close()


async def test_mqtt_test_connects_with_its_own_client_id():
    broker = await FakeBroker(users={"u": "p"}).start()
    studio = Studio()
    try:
        config = MQTTConfig(host="127.0.0.1", port=broker.port, username="u", password="p")
        result = await studio.test_mqtt(config)
        assert result.ok, result
        assert result.message == f"connected to 127.0.0.1:{broker.port}"
        assert broker.client_ids == [f"{studio.mqtt.default_client_id}-test"]
        assert studio.mqtt.config.host == "localhost"  # not applied

        result = await studio.test_mqtt(config.model_copy(update={"password": "wrong"}))
        assert not result.ok and "connection refused by the broker" in result.message
    finally:
        await studio.close()
        await broker.stop()


async def test_mqtt_test_uses_the_saved_password():
    broker = await FakeBroker(users={"u": "p"}).start()
    studio = Studio()
    try:
        studio.set_mqtt(MQTTConfig(host="127.0.0.1", port=broker.port, username="u", password="p"))
        result = await studio.test_mqtt(studio.mqtt.config.model_copy(update={"password": None}))
        assert result.ok, result
    finally:
        await studio.close()
        await broker.stop()


async def test_mqtt_test_failures():
    studio = Studio()
    port = free_port()
    result = await studio.test_mqtt(MQTTConfig(host="127.0.0.1", port=port))
    assert not result.ok and f"cannot connect to 127.0.0.1:{port}" in result.message

    broker = await FakeBroker(hang_up=True).start()
    try:
        result = await studio.test_mqtt(MQTTConfig(host="127.0.0.1", port=broker.port))
        assert not result.ok and "check the port and the TLS setting" in result.message
    finally:
        await broker.stop()

    result = await studio.test_mqtt(
        MQTTConfig(host="127.0.0.1", tls=True, ca_file="/nowhere/ca.pem")
    )
    assert not result.ok and "ca_file '/nowhere/ca.pem' not found" in result.message
