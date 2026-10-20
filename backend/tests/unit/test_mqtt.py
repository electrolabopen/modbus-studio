"""MQTT exporter: topics, payloads, settings and error messages."""

import json
import socket
import ssl
from datetime import datetime

import pytest
from pydantic import ValidationError

from modbus_studio.core.influx import Sample
from modbus_studio.core.mqtt import MqttExporter, changed, describe_error, payload_for, topic_for
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


# -- publishing on change (report by exception) ----------------------------


def exporter(**settings) -> MqttExporter:
    """An exporter that queues messages without a client (nothing is sent)."""
    e = MqttExporter()
    e.config = MQTTConfig(**{"enabled": True, "publish_mode": "on_change", **settings})
    return e


def published(e: MqttExporter) -> list[tuple[str, object]]:
    return [(topic, json.loads(payload)["value"]) for topic, payload in e._buffer]


def values(e: MqttExporter) -> list[object]:
    return [value for _, value in published(e)]


def times(e: MqttExporter, start: float = 1000.0) -> list[float]:
    """When each queued value was polled, in seconds after ``start``."""
    stamps = (json.loads(p)["timestamp"].replace("Z", "+00:00") for _, p in e._buffer)
    return [round(datetime.fromisoformat(t).timestamp() - start, 3) for t in stamps]


def feed(e: MqttExporter, series, start: float = 1000.0, step: float = 0.05, **fields) -> None:
    """One sample per poll, ``step`` seconds apart."""
    for i, value in enumerate(series):
        e.offer([sample(poll_id="w", value=value, timestamp=start + i * step, **fields)])


@pytest.mark.parametrize(
    ("old", "new", "deadband", "expected"),
    [
        (1, 1, 0, False),
        (1, 2, 0, True),
        (21.5, 21.6, 0.1, False),  # 0.10000000000000142: scaling noise, not above 0.1
        (21.5, 21.7, 0.1, True),
        (21.5, 21.3, 0.1, True),  # either direction
        (100, 105, 5, False),
        (100, 106, 5, True),
        (False, True, 10, True),  # bits flip whatever the deadband
        (True, True, 0, False),
        (1, 1.0, 0, True),  # the data type changed
        (True, 1, 0, True),
    ],
)
def test_changed(old, new, deadband, expected):
    assert changed(old, new, deadband) is expected


def test_every_poll_is_the_default_and_publishes_repeats():
    e = exporter(publish_mode="every_poll")
    assert MQTTConfig().publish_mode == "every_poll"
    feed(e, [1, 1, 1, 2, 2])
    assert values(e) == [1, 1, 1, 2, 2]
    assert e.status.unchanged == 0


@pytest.mark.parametrize("offset", [0.0, 0.01, 0.025, 0.049])
def test_issue_1_a_100_ms_bit_polled_every_50_ms_gives_two_messages(offset):
    """Issue #1: a door bit high for 100 ms, polled every 50 ms. Each poll of the
    window only says whether the bit is set at that moment."""
    e = exporter()
    scans = [i * 0.05 for i in range(40)]  # 2 s of polls
    rise = 1.0 + offset
    series = [rise <= t < rise + 0.1 for t in scans]
    assert series.count(True) == 2  # the pulse is caught by exactly two polls

    feed(e, series[:1])  # the state at start-up is published once
    assert values(e) == [False]
    feed(e, series[1:], start=1000.05)
    assert values(e)[1:] == [True, False]  # exactly the rising and the falling edge
    assert e.status.unchanged == len(series) - 3
    assert e.status.pending == 3


def test_every_poll_on_the_same_pulse_publishes_every_scan():
    e = exporter(publish_mode="every_poll")
    feed(e, [1.0 <= i * 0.05 < 1.1 for i in range(40)])
    assert len(values(e)) == 40


def test_exporter_deadband():
    e = exporter(deadband=0.5)
    feed(e, [20.0, 20.3, 20.5, 20.6, 20.2, 21.2, 21.0])
    # Compared with the last value published, so slow drifts are not lost.
    assert values(e) == [20.0, 20.6, 21.2]


def test_a_register_deadband_replaces_the_exporters():
    e = exporter(deadband=0.5)
    feed(e, [20.0, 20.3, 20.6, 22.0, 22.1], deadband=2.0)
    assert values(e) == [20.0, 22.1]
    e = exporter(deadband=0.5)
    feed(e, [20.0, 20.3, 20.3], deadband=0.0)
    assert values(e) == [20.0, 20.3]


def test_values_are_tracked_per_window_and_address():
    e = exporter()
    for poll_id, address in [("a", 1), ("a", 2), ("b", 1), ("a", 1)]:
        e.offer([sample(poll_id=poll_id, address=address, alias="", value=7)])
    assert [t for t, _ in published(e)] == [
        "modbus-studio/Plant/1/1",
        "modbus-studio/Plant/1/2",
        "modbus-studio/Plant/1/1",
    ]


def test_heartbeat_republishes_unchanged_values():
    e = exporter(heartbeat_s=1)
    feed(e, [5] * 50, step=0.1)  # 4.9 s
    assert times(e) == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_heartbeat_counts_from_the_last_message():
    e = exporter(heartbeat_s=1)
    feed(e, [5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6], step=0.1)
    # 6 is published at 0.5 s; the next heartbeat is at 1.5 s, not 1.0 s.
    assert times(e) == [0.0, 0.5, 1.5]


def test_a_clock_set_back_does_not_silence_the_heartbeat():
    e = exporter(heartbeat_s=60)
    feed(e, [5], start=1000.0)
    feed(e, [5], start=900.0)
    assert values(e) == [5, 5]


def test_without_heartbeat_an_unchanged_value_is_never_repeated():
    e = exporter()
    feed(e, [5] * 100, step=10)
    assert values(e) == [5]


def test_a_failed_read_makes_the_next_value_a_change():
    e = exporter()
    feed(e, [3, 3])
    e.forget("w")  # the whole window failed
    feed(e, [3, 3])
    assert values(e) == [3, 3]


def test_a_failed_value_makes_only_that_value_a_change():
    e = exporter()
    for addr in (1, 2):
        e.offer([sample(poll_id="w", address=addr, alias="", value=0)])
    e.forget("w", [2])
    for addr in (1, 2):
        e.offer([sample(poll_id="w", address=addr, alias="", value=0)])
    assert [t for t, _ in published(e)][-1] == "modbus-studio/Plant/1/2"
    assert len(published(e)) == 3


def test_a_value_json_cannot_carry_counts_as_a_failed_read():
    e = exporter()
    feed(e, [1.0, float("nan"), 1.0])
    assert values(e) == [1.0, 1.0]


def test_a_renamed_value_is_published_on_its_new_topic():
    e = exporter()
    e.offer([sample(poll_id="w", alias="t1", value=1)])
    e.offer([sample(poll_id="w", alias="t2", value=1)])
    e.offer([sample(poll_id="w", alias="t2", unit="K", value=1)])
    assert [t for t, _ in published(e)] == [
        "modbus-studio/Plant/1/t1",
        "modbus-studio/Plant/1/t2",
        "modbus-studio/Plant/1/t2",
    ]


def test_aliased_only_applies_before_the_change_check():
    e = exporter(aliased_only=True)
    feed(e, [1, 2], alias="")
    assert values(e) == []
    assert e.status.unchanged == 0


@pytest.mark.parametrize(
    "settings",
    [
        {"publish_mode": "sometimes"},
        {"deadband": -1},
        {"deadband": float("inf")},
        {"deadband": float("nan")},
        {"heartbeat_s": -1},
        {"heartbeat_s": 86_401},
    ],
)
def test_invalid_on_change_settings(settings):
    with pytest.raises(ValidationError):
        MQTTConfig(**settings)


def test_view_shows_the_on_change_settings():
    config = MQTTConfig(publish_mode="on_change", deadband=0.5, heartbeat_s=60)
    view = MQTTConfigView.of(config).model_dump()
    assert (view["publish_mode"], view["deadband"], view["heartbeat_s"]) == ("on_change", 0.5, 60)
