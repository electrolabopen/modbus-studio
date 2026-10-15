import math

import pytest

from modbus_studio.core.codec import (
    ByteOrder,
    CodecError,
    DataType,
    RegisterFormat,
    decode,
    decode_table,
    encode,
    format_value,
    from_engineering,
    register_count,
    to_engineering,
)

A, C, B, D = ByteOrder.ABCD, ByteOrder.CDAB, ByteOrder.BADC, ByteOrder.DCBA


# Reference vectors written out by hand from the byte layout, not produced by the codec.
@pytest.mark.parametrize(
    ("dtype", "value", "order", "registers"),
    [
        # 10.0 as IEEE-754 single = 0x41200000
        (DataType.FLOAT32, 10.0, A, [0x4120, 0x0000]),
        (DataType.FLOAT32, 10.0, C, [0x0000, 0x4120]),
        (DataType.FLOAT32, 10.0, B, [0x2041, 0x0000]),
        (DataType.FLOAT32, 10.0, D, [0x0000, 0x2041]),
        (DataType.UINT32, 0x12345678, A, [0x1234, 0x5678]),
        (DataType.UINT32, 0x12345678, C, [0x5678, 0x1234]),
        (DataType.UINT32, 0x12345678, B, [0x3412, 0x7856]),
        (DataType.UINT32, 0x12345678, D, [0x7856, 0x3412]),
        (DataType.INT32, -2, A, [0xFFFF, 0xFFFE]),
        (DataType.INT32, -2, C, [0xFFFE, 0xFFFF]),
        (DataType.UINT64, 0x0102030405060708, A, [0x0102, 0x0304, 0x0506, 0x0708]),
        (DataType.UINT64, 0x0102030405060708, C, [0x0708, 0x0506, 0x0304, 0x0102]),
        (DataType.UINT64, 0x0102030405060708, B, [0x0201, 0x0403, 0x0605, 0x0807]),
        (DataType.UINT64, 0x0102030405060708, D, [0x0807, 0x0605, 0x0403, 0x0201]),
        (DataType.INT64, -1, A, [0xFFFF] * 4),
        # 1.0 as IEEE-754 double = 0x3FF0000000000000
        (DataType.FLOAT64, 1.0, A, [0x3FF0, 0, 0, 0]),
        (DataType.FLOAT64, 1.0, D, [0, 0, 0, 0xF03F]),
        (DataType.INT16, -1, A, [0xFFFF]),
        (DataType.INT16, -32768, A, [0x8000]),
        (DataType.UINT16, 0x1234, A, [0x1234]),
        (DataType.UINT16, 0x1234, C, [0x1234]),  # word swap is meaningless for one word
        (DataType.UINT16, 0x1234, B, [0x3412]),
        (DataType.UINT16, 0x1234, D, [0x3412]),
    ],
)
def test_reference_vectors(dtype, value, order, registers):
    assert encode(value, dtype, order) == registers
    assert decode(registers, dtype, order) == value


@pytest.mark.parametrize("order", list(ByteOrder))
@pytest.mark.parametrize(
    ("dtype", "values"),
    [
        (DataType.INT16, [-32768, -1, 0, 1, 32767]),
        (DataType.UINT16, [0, 1, 65535]),
        (DataType.INT32, [-(2**31), -123456789, 0, 2**31 - 1]),
        (DataType.UINT32, [0, 3_000_000_000, 2**32 - 1]),
        (DataType.INT64, [-(2**63), 0, 2**63 - 1]),
        (DataType.UINT64, [0, 2**64 - 1]),
        (DataType.FLOAT32, [0.0, -1.5, 3.25, 2.0**-20]),
        (DataType.FLOAT64, [0.0, math.pi, -1e300]),
    ],
)
def test_roundtrip(dtype, values, order):
    for value in values:
        regs = encode(value, dtype, order)
        assert len(regs) == register_count(dtype)
        assert all(0 <= r <= 0xFFFF for r in regs)
        assert decode(regs, dtype, order) == value


def test_float_nan_and_inf():
    assert math.isnan(decode(encode(float("nan"), DataType.FLOAT32), DataType.FLOAT32))
    assert decode(encode(float("inf"), DataType.FLOAT64), DataType.FLOAT64) == float("inf")


@pytest.mark.parametrize(
    ("dtype", "value"),
    [
        (DataType.INT16, 32768),
        (DataType.UINT16, -1),
        (DataType.UINT32, 2**32),
        (DataType.INT32, 1.5),
    ],
)
def test_encode_rejects_out_of_range(dtype, value):
    with pytest.raises(CodecError):
        encode(value, dtype)


def test_decode_needs_enough_registers():
    with pytest.raises(CodecError):
        decode([0x4120], DataType.FLOAT32)


def test_decode_rejects_invalid_register_values():
    with pytest.raises(CodecError):
        decode([0x10000], DataType.UINT16)


def test_format_value():
    assert format_value(255, DataType.HEX16) == "0x00FF"
    assert format_value(0xA5F0, DataType.BIN16) == "1010 0101 1111 0000"
    assert format_value(-5, DataType.INT16) == "-5"
    assert format_value(0.1, DataType.FLOAT32, decimals=3) == "0.100"
    assert format_value(1 / 3, DataType.FLOAT32) == "0.3333333"


def test_scale_to_and_from_engineering():
    fmt = RegisterFormat(DataType.INT16, scale=0.1, unit="°C")
    assert to_engineering(-235, fmt) == pytest.approx(-23.5)
    assert from_engineering(-23.5, fmt) == encode(-235, DataType.INT16)
    # The nearest raw value is written when the scaled value is not exact.
    assert from_engineering(23.46, fmt) == [235]


def test_scale_is_ignored_for_bit_patterns():
    fmt = RegisterFormat(DataType.HEX16, scale=10)
    assert to_engineering(0x00FF, fmt) == 0x00FF
    assert from_engineering(0x00FF, fmt) == [0x00FF]


def test_unit_scale_keeps_integers():
    assert to_engineering(7, RegisterFormat()) == 7
    assert isinstance(to_engineering(7, RegisterFormat()), int)


def test_scaled_float_register():
    fmt = RegisterFormat(DataType.FLOAT32, ByteOrder.CDAB, scale=1000.0, unit="mV")
    regs = from_engineering(2500.0, fmt)
    assert decode(regs, DataType.FLOAT32, ByteOrder.CDAB) == 2.5


@pytest.mark.parametrize("scale", [0, float("nan"), float("inf")])
def test_invalid_scale(scale):
    with pytest.raises(CodecError):
        RegisterFormat(scale=scale)


def test_decode_table_mixed_formats():
    regs = [7, 0x4120, 0x0000, 0xFFFF, 0x0000, 0x4120]
    formats = {
        101: RegisterFormat(DataType.FLOAT32, unit="bar", alias="pressure"),
        104: RegisterFormat(DataType.FLOAT32, ByteOrder.CDAB),
    }
    cells = decode_table(regs, start_address=100, formats=formats)
    assert [c.address for c in cells] == [100, 101, 102, 103, 104, 105]
    assert cells[0].value == 7
    assert cells[1].value == 10.0 and cells[1].fmt.alias == "pressure"
    assert cells[2].covered_by == 101 and cells[2].value is None
    assert cells[3].value == -1
    assert cells[4].value == 10.0 and cells[5].covered_by == 104


def test_decode_table_incomplete_trailing_value():
    cells = decode_table([1, 0x4120], 0, {1: RegisterFormat(DataType.FLOAT64)})
    assert cells[0].value == 1
    assert cells[1].value is None and cells[1].error
    assert len(cells) == 2
