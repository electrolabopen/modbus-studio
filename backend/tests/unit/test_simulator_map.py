import pytest

from modbus_studio.core.codec import ByteOrder, DataType, decode
from modbus_studio.simulator import CONST_INT32, CONST_UINT32, dynamic_registers


def words(regs, start, n):
    return [regs[start + i] for i in range(n)]


def test_dynamic_registers_at_known_time():
    regs = dynamic_registers(5.0)  # quarter period of the 20 s sine -> peak
    assert regs[0] == 5
    assert regs[1] == 50
    for start, order in [
        (10, ByteOrder.ABCD),
        (12, ByteOrder.CDAB),
        (14, ByteOrder.BADC),
        (16, ByteOrder.DCBA),
    ]:
        assert decode(words(regs, start, 2), DataType.FLOAT32, order) == pytest.approx(100.0)
    assert decode(words(regs, 20, 4), DataType.FLOAT64) == pytest.approx(100.0)
    assert decode(words(regs, 24, 2), DataType.INT32) == CONST_INT32
    assert decode(words(regs, 26, 2), DataType.UINT32, ByteOrder.CDAB) == CONST_UINT32


def test_temperature_is_signed_and_scaled():
    # minimum of 50 + 100*sin(2*pi*t/60) is at t = 45 s -> -50.0 °C -> raw -500
    assert decode([dynamic_registers(45.0)[2]], DataType.INT16) == -500
