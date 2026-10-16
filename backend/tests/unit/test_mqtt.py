"""MQTT exporter: topics, payloads, settings and error messages."""

import json
import socket
import ssl

import pytest
from pydantic import ValidationError

from modbus_studio.core.influx import Sample
from modbus_studio.core.mqtt import describe_error, payload_for, topic_for
from modbus_studio.models.exporters import ExportersConfig, MQTTConfig, MQTTConfigView

DEFAULT_TOPIC = MQTTConfig().topic


def sample(**overrides) -> Sample:
    values = {
        "window": "Simulator",
        "connection": "Plant",
        "device": 1,
        "address": 2,
        "alias": "temperature",
        "unit": "°C",
        "value": 21.5,
        "timestamp": 1_800_000_000.25,
    }
    return Sample(**{**values, **overrides})


def test_default_topic():
    assert topic_for(DEFAULT_TOPIC, sample()) == "modbus-studio/Plant/1/temperature"


def test_alias_falls_back_to_the_address():
    assert topic_for(DEFAULT_TOPIC, sample(alias="")) == "modbus-studio/Plant/1/2"


def test_every_placeholder():
    template = "{window}/{connection}/{device}/{address}/{alias}/{unit}"
    assert topic_for(template, sample()) == "Simulator/Plant/1/2/temperature/°C"


def test_values_never_add_levels_or_wildcards():
    s = sample(connection="line 1/PLC", alias="a+b#c")
    assert topic_for(DEFAULT_TOPIC, s) == "modbus-studio/line 1_PLC/1/a_b_c"


def test_payload():
    body = json.loads(payload_for(sample()))
    assert body == {
        "value": 21.5,
        "unit": "°C",
        "timestamp": "2027-01-15T08:00:00.250Z",
        "alias": "temperature",
        "address": 2,
        "device": 1,
        "connection": "Plant",
        "window": "Simulator",
    }


def test_payload_is_utf8_json():
    assert "°C".encode() in payload_for(sample())


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1153 * 0.1, 115.3), (-123456789, -123456789), (True, True), (0, 0)],
)
def test_payload_values(value, expected):
    got = json.loads(payload_for(sample(value=value)))["value"]
    assert got == expected and type(got) is type(expected)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_values_json_cannot_carry_are_skipped(value):
    assert payload_for(sample(value=value)) is None


@pytest.mark.parametrize(
    "topic",
    ["plant/{alias}", "{window}/{connection}/{device}/{address}/{alias}/{unit}", "fixed/topic"],
)
def test_valid_topics(topic):
    assert MQTTConfig(topic=topic).topic == topic


@pytest.mark.parametrize(
    ("topic", "message"),
    [
        ("", "must not be empty"),
        ("plant/+/x", "wildcards"),
        ("plant/#", "wildcards"),
        ("$SYS/x", "reserved"),
        ("plant/{name}", "unknown placeholder {name}"),
        ("plant/{alias:>10}", "takes no format"),
        ("plant/{alias", "topic:"),
    ],
)
def test_invalid_topics(topic, message):
    with pytest.raises(ValidationError, match=message.replace("{", r"\{").replace("+", r"\+")):
        MQTTConfig(topic=topic)


def test_qos_is_0_1_or_2():
    with pytest.raises(ValidationError):
        MQTTConfig(qos=3)


def test_view_withholds_the_password():
    view = MQTTConfigView.of(MQTTConfig(username="u", password="secret"))
    assert view.password_set is True
    assert "secret" not in view.model_dump_json()


def test_exports_without_secrets():
    config = ExportersConfig(mqtt=MQTTConfig(password="secret"))
    assert config.without_secrets().mqtt.password is None
    assert config.mqtt.password == "secret"


@pytest.mark.parametrize(
    ("exc", "text"),
    [
        (ConnectionRefusedError(), "cannot connect to broker:1883: connection refused"),
        (socket.gaierror(-2, "Name or service not known"), "unknown host (Name or service"),
        (TimeoutError(), "no answer from broker:1883 (timeout)"),
        (ssl.SSLError(1, "wrong version number"), "TLS error with broker:1883"),
    ],
)
def test_connection_errors(exc, text):
    assert text in describe_error(exc, "broker", 1883)
