"""API representation of how registers are displayed."""

from __future__ import annotations

import math

from pydantic import BaseModel, Field, field_validator

from ..core.codec import ByteOrder, DataType, RegisterFormat


class RegisterFormatModel(BaseModel):
    dtype: DataType = DataType.INT16
    order: ByteOrder = ByteOrder.ABCD
    scale: float = 1.0
    unit: str = Field(default="", max_length=32)
    alias: str = Field(default="", max_length=64)

    @field_validator("scale")
    @classmethod
    def _check_scale(cls, value: float) -> float:
        if not math.isfinite(value) or value == 0:
            raise ValueError("scale must be a finite, non-zero number")
        return value

    def to_codec(self) -> RegisterFormat:
        return RegisterFormat(self.dtype, self.order, self.scale, self.unit, self.alias)
