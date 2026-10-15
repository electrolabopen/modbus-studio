import pytest
from pydantic import TypeAdapter, ValidationError

from modbus_studio.models import (
    ConnectionConfig,
    PollDefinition,
    ReadFunction,
    RtuConnection,
    RtuOverTcpConnection,
    TcpConnection,
)

adapter = TypeAdapter(ConnectionConfig)


def test_connection_discriminator():
    assert isinstance(
        adapter.validate_python({"type": "tcp", "id": "a", "host": "h"}), TcpConnection
    )
    assert isinstance(
        adapter.validate_python({"type": "rtu_over_tcp", "id": "a", "host": "h"}),
        RtuOverTcpConnection,
    )
    rtu = adapter.validate_python({"type": "rtu", "id": "a", "serial_port": "/dev/ttyUSB0"})
    assert isinstance(rtu, RtuConnection)
    assert (rtu.baudrate, rtu.parity, rtu.stopbits) == (19200, "E", 1)


def test_connection_id_is_restricted():
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "tcp", "id": "bad id/", "host": "h"})


@pytest.mark.parametrize(
    ("function", "limit"),
    [
        (ReadFunction.READ_COILS, 2000),
        (ReadFunction.READ_DISCRETE_INPUTS, 2000),
        (ReadFunction.READ_HOLDING_REGISTERS, 125),
        (ReadFunction.READ_INPUT_REGISTERS, 125),
    ],
)
def test_quantity_limits(function, limit):
    PollDefinition(id="p", connection_id="c", function=function, quantity=limit)
    with pytest.raises(ValidationError):
        PollDefinition(id="p", connection_id="c", function=function, quantity=limit + 1)


def test_address_space_overflow():
    PollDefinition(id="p", connection_id="c", address=65535, quantity=1)
    with pytest.raises(ValidationError):
        PollDefinition(id="p", connection_id="c", address=65535, quantity=2)
