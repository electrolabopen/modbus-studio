"""Definition of a polling window."""

from __future__ import annotations

import uuid
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .format import RegisterFormatModel


class ReadFunction(IntEnum):
    READ_COILS = 1
    READ_DISCRETE_INPUTS = 2
    READ_HOLDING_REGISTERS = 3
    READ_INPUT_REGISTERS = 4

    @property
    def is_bit(self) -> bool:
        return self in (ReadFunction.READ_COILS, ReadFunction.READ_DISCRETE_INPUTS)

    @property
    def max_quantity(self) -> int:
        # Limits from the Modbus Application Protocol specification v1.1b3, section 6.
        return 2000 if self.is_bit else 125


def new_id() -> str:
    return uuid.uuid4().hex[:8]


# Fields that change what is sent on the wire. Changing anything else (name,
# formats) is applied without restarting the window or resetting its counters.
POLLING_FIELDS = (
    "connection_id",
    "device_id",
    "function",
    "address",
    "quantity",
    "scan_rate_ms",
    "enabled",
)


class PollDefinition(BaseModel):
    id: str = Field(
        default_factory=new_id, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    connection_id: str
    name: str = ""
    device_id: int = Field(default=1, ge=0, le=255)
    function: ReadFunction = ReadFunction.READ_HOLDING_REGISTERS
    # Zero-based protocol address (the value sent in the PDU).
    address: int = Field(default=0, ge=0, le=0xFFFF)
    quantity: int = Field(default=10, ge=1)
    scan_rate_ms: int = Field(default=1000, ge=10, le=3_600_000)
    enabled: bool = True
    # Display format for registers without an entry in ``formats``.
    default_format: RegisterFormatModel = Field(default_factory=RegisterFormatModel)
    # Per-address format, alias, scale and unit, keyed by protocol address.
    formats: dict[int, RegisterFormatModel] = Field(default_factory=dict)

    def polling_key(self) -> tuple[Any, ...]:
        return tuple(getattr(self, f) for f in POLLING_FIELDS)

    @model_validator(mode="after")
    def _check_range(self) -> PollDefinition:
        if self.quantity > self.function.max_quantity:
            raise ValueError(
                f"FC{self.function.value:02d} allows at most {self.function.max_quantity} items"
            )
        if self.address + self.quantity > 0x10000:
            raise ValueError("address + quantity exceeds the 65536 address space")
        return self
