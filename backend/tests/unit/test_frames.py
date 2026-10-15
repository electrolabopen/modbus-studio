"""Frame descriptions, checked against frames written out by hand from the spec."""

from modbus_studio.core.frames import FrameInfo, crc16, describe

# MODBUS over Serial Line guide: read 10 holding registers from slave 1.
RTU_REQUEST = bytes.fromhex("01 03 00 00 00 0A C5 CD")


def test_crc16_reference_frame():
    assert crc16(RTU_REQUEST[:-2]) == 0xCDC5  # sent low byte first: C5 CD


def test_rtu_request():
    assert describe(RTU_REQUEST, "rtu") == FrameInfo(device_id=1, function=3)


def test_rtu_bad_crc():
    info = describe(RTU_REQUEST[:-1] + b"\x00", "rtu")
    assert info.device_id == 1 and info.error == "bad CRC 00C5, expected CDC5"


def test_rtu_exception_response():
    body = bytes([0x11, 0x83, 0x02])
    frame = body + crc16(body).to_bytes(2, "little")
    assert describe(frame, "rtu") == FrameInfo(device_id=0x11, function=3, exception_code=2)


def test_tcp_request_and_exception():
    request = bytes.fromhex("00 2A 00 00 00 06 01 03 00 00 00 0A")
    assert describe(request, "tcp") == FrameInfo(1, 3, None, 0x2A, None)
    exception = bytes.fromhex("00 2A 00 00 00 03 01 86 03")
    assert describe(exception, "tcp") == FrameInfo(1, 6, 3, 0x2A, None)


def test_tcp_header_problems():
    assert describe(bytes.fromhex("00 01 00 00 00 09 01 03 00"), "tcp").error == (
        "MBAP length 9, frame carries 3"
    )
    assert describe(bytes.fromhex("00 01 00 01 00 02 01 03"), "tcp").error == (
        "protocol id is not 0"
    )
    assert describe(b"\x00\x01", "tcp").error == "short frame (2 bytes)"
    assert describe(b"\x01\x03", "rtu").error == "short frame (2 bytes)"
