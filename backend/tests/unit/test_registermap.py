import pytest

from modbus_studio.core.codec import ByteOrder, DataType
from modbus_studio.core.registermap import RegisterMapError, parse_register_map


def errors(text: str) -> list[tuple[int, str]]:
    with pytest.raises(RegisterMapError) as info:
        parse_register_map(text)
    return [(e.line, e.message) for e in info.value.errors]


def test_full_row_and_defaults():
    rows = parse_register_map(
        "address,alias,type,byte_order,scale,unit\n10,flow,float32,cdab,1,m3/h\n12,,,,,\n"
    )
    assert [(r.line, r.address, r.alias, r.dtype, r.order, r.scale, r.unit) for r in rows] == [
        (2, 10, "flow", DataType.FLOAT32, ByteOrder.CDAB, 1.0, "m3/h"),
        (3, 12, "", DataType.INT16, ByteOrder.ABCD, 1.0, ""),
    ]
    assert rows[0].last_address == 11


def test_spreadsheet_export_with_semicolons_bom_and_comments():
    text = "﻿# exported\nUnit;Address;Scale;Alias\n°C;2;0,1;temperature\n\n# end\n"
    [row] = parse_register_map(text)
    assert (row.line, row.address, row.scale, row.unit, row.alias) == (
        3,
        2,
        0.1,
        "°C",
        "temperature",
    )


def test_problems_are_reported_per_line():
    text = (
        "address,type,scale\n"
        "x,int16,1\n"  # 2
        "5,float16,1\n"  # 3
        "6,int16,0\n"  # 4
        "10,float32,1\n"  # 5
        "11,int16,1\n"  # 6 overlaps 10-11
        "20,int16,1\n"  # 7
        "20,uint16,1\n"  # 8 repeats 20
    )
    found = errors(text)
    assert [line for line, _ in found] == [2, 3, 4, 6, 8]
    assert "address 'x' is not a number" in found[0][1]
    assert "unknown type 'float16'" in found[1][1]
    assert "scale '0' must be a non-zero number" in found[2][1]
    assert found[3][1] == "address 11 overlaps the float32 at 10 (10-11) on line 5"
    assert found[4][1] == "address 20 repeats address on line 7"


def test_header_problems():
    assert errors("alias,type\nx,int16\n") == [(1, "missing the 'address' column")]
    assert "unknown column(s) colour" in errors("address,colour\n1,red\n")[0][1]
    assert errors("# only a comment\n") == [(1, "the file is empty")]
    assert errors("address\n") == [(1, "no rows after the header")]
    assert errors("address,alias\n1,a,b\n") == [(2, "3 fields, the header has 2")]
