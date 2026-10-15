"""Workspace file: the connections, polling windows and exporters of a session, as JSON.

The state file keeps exporter credentials (tokens) so a restart can reconnect; a
workspace downloaded from the API leaves them out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .connection import ConnectionConfig
from .exporters import ExportersConfig
from .poll import PollDefinition


class Workspace(BaseModel):
    version: Literal[1] = 1
    connections: list[ConnectionConfig] = Field(default_factory=list)
    polls: list[PollDefinition] = Field(default_factory=list)
    exporters: ExportersConfig = Field(default_factory=ExportersConfig)

    @model_validator(mode="after")
    def _check_references(self) -> Workspace:
        ids = [c.id for c in self.connections]
        if len(ids) != len(set(ids)):
            raise ValueError("connection ids must be unique")
        poll_ids = [p.id for p in self.polls]
        if len(poll_ids) != len(set(poll_ids)):
            raise ValueError("poll ids must be unique")
        for poll in self.polls:
            if poll.connection_id not in ids:
                raise ValueError(f"poll {poll.id!r} uses unknown connection {poll.connection_id!r}")
        return self

    @classmethod
    def load(cls, path: Path) -> Workspace:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
