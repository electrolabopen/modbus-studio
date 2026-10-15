"""Keep the session's workspace on disk so a restart does not lose it.

The state file is rewritten atomically (temporary file + rename), so a crash or a
power cut on a gateway leaves either the old or the new version, never half of one.
Saves are coalesced: several changes within ``delay_s`` produce one write.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from ..models.workspace import Workspace

log = logging.getLogger(__name__)


class StateFile:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Workspace | None:
        """Return the saved workspace, or None when there is none.

        An unreadable file is moved aside instead of stopping the server, which would
        otherwise restart in a loop under ``restart: unless-stopped``. Nothing is lost:
        the bad file stays next to the new one for inspection.
        """
        if not self.path.exists():
            return None
        try:
            return Workspace.load(self.path)
        except (OSError, UnicodeDecodeError, ValidationError) as exc:
            aside = self.path.with_name(
                f"{self.path.name}.invalid-{time.strftime('%Y%m%d-%H%M%S')}"
            )
            with contextlib.suppress(OSError):
                self.path.replace(aside)
            log.error(
                "could not read %s, moved to %s and starting without it: %s", self.path, aside, exc
            )
            return None

    def save(self, workspace: Workspace) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(workspace.model_dump_json(indent=2))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.path)


class AutoSaver:
    """Write ``export()`` to ``state`` shortly after each change."""

    def __init__(
        self, state: StateFile, export: Callable[[], Workspace], delay_s: float = 0.5
    ) -> None:
        self._state = state
        self._export = export
        self._delay_s = delay_s
        self._pending: asyncio.TimerHandle | None = None

    def schedule(self) -> None:
        if self._pending is None:
            self._pending = asyncio.get_running_loop().call_later(self._delay_s, self.flush)

    def flush(self) -> None:
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        try:
            self._state.save(self._export())
        except OSError as exc:
            # Keep running: losing the polling session over a full disk would be worse.
            log.error("could not save workspace to %s: %s", self._state.path, exc)
