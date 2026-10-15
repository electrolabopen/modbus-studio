"""Application service: connections, polling windows and writes as one unit.

The API layer only translates HTTP/WebSocket to calls on :class:`Studio`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..models.connection import ConnectionConfig
from ..models.poll import PollDefinition, ReadFunction
from ..models.views import (
    Cell,
    ConnectionView,
    FormatPatch,
    PollData,
    PollView,
    RawWrite,
    TrafficEntryView,
    WindowWrite,
    WritePlan,
)
from ..models.workspace import Workspace
from .codec import (
    CodecError,
    decode,
    decode_table,
    format_value,
    from_engineering,
    register_count,
    to_engineering,
)
from .connection import ClientFactory, Connection, ConnectionManager, default_client_factory
from .poller import PollManager, PollResult, PollTask
from .traffic import TrafficEntry, TrafficLog


class StudioError(Exception):
    pass


class NotFoundError(StudioError):
    pass


class ConflictError(StudioError):
    pass


class InvalidRequestError(StudioError):
    pass


class ForbiddenError(StudioError):
    pass


# Changing these fields does not touch the physical link, so polling keeps running.
_LIVE_CONNECTION_FIELDS = {"name", "read_only"}


class Studio:
    def __init__(
        self, traffic_buffer: int = 5000, client_factory: ClientFactory = default_client_factory
    ) -> None:
        self.traffic = TrafficLog(maxlen=traffic_buffer)
        self.connections = ConnectionManager(self.traffic, client_factory)
        self.polls = PollManager(self.connections)
        self._change_listeners: list[Callable[[], None]] = []

    def subscribe_changes(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` whenever connections or windows are added, edited or removed."""
        self._change_listeners.append(listener)

    def _changed(self) -> None:
        for listener in self._change_listeners:
            listener()

    def export_workspace(self) -> Workspace:
        return Workspace(
            connections=[c.config for c in self.connections.all()],
            polls=[t.definition for t in self.polls.all()],
        )

    async def close(self) -> None:
        await self.polls.stop_all()
        await self.connections.close_all()

    # -- connections -------------------------------------------------------

    def _connection(self, connection_id: str) -> Connection:
        try:
            return self.connections.get(connection_id)
        except KeyError as exc:
            raise NotFoundError(f"unknown connection {connection_id!r}") from exc

    def connection_view(self, connection_id: str) -> ConnectionView:
        conn = self._connection(connection_id)
        return ConnectionView(
            config=conn.config,
            state=conn.state.value,
            stats=conn.stats.as_dict(),
            last_error=conn.last_error,
        )

    def load_workspace(self, workspace: Workspace) -> None:
        """Add a workspace's connections and windows to the current session."""
        for config in workspace.connections:
            self.add_connection(config)
        for definition in workspace.polls:
            self.add_poll(definition)

    def list_connections(self) -> list[ConnectionView]:
        return [self.connection_view(c.id) for c in self.connections.all()]

    def add_connection(self, config: ConnectionConfig) -> ConnectionView:
        try:
            self.connections.add(config)
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        self._changed()
        return self.connection_view(config.id)

    async def update_connection(self, config: ConnectionConfig) -> ConnectionView:
        """Replace a connection's settings; windows using it are restarted on the new one."""
        current = self._connection(config.id)
        if current.config.model_dump(exclude=_LIVE_CONNECTION_FIELDS) == config.model_dump(
            exclude=_LIVE_CONNECTION_FIELDS
        ):
            current.config = config
            self._changed()
            return self.connection_view(config.id)
        definitions = [t.definition for t in self.polls.using_connection(config.id)]
        for definition in definitions:
            await self.polls.remove(definition.id)
        await self.connections.remove(config.id)
        self.connections.add(config)
        for definition in definitions:
            self.polls.add(definition)
        self._changed()
        return self.connection_view(config.id)

    async def remove_connection(self, connection_id: str, cascade: bool = False) -> None:
        self._connection(connection_id)
        users = self.polls.using_connection(connection_id)
        if users and not cascade:
            raise ConflictError(
                f"connection is used by {len(users)} polling window(s); delete them first"
            )
        for task in users:
            await self.polls.remove(task.definition.id)
        await self.connections.remove(connection_id)
        self._changed()

    @staticmethod
    def _check_writable(conn: Connection) -> None:
        if conn.config.read_only:
            name = conn.config.name or conn.id
            raise ForbiddenError(f"connection {name!r} is read-only; writes are disabled")

    async def write_raw(self, connection_id: str, req: RawWrite) -> None:
        conn = self._connection(connection_id)
        self._check_writable(conn)
        if req.function in (5, 15):
            if any(v not in (0, 1) for v in req.values):
                raise InvalidRequestError("coil values must be 0 or 1")
            bits = [bool(v) for v in req.values]
            if req.function == 5:
                if len(bits) != 1:
                    raise InvalidRequestError("FC05 writes exactly one coil")
                await conn.write_coil(req.device_id, req.address, bits[0])
            else:
                await conn.write_coils(req.device_id, req.address, bits)
            return
        if any(not 0 <= v <= 0xFFFF for v in req.values):
            raise InvalidRequestError("register values must be 0..65535")
        if req.function == 6:
            if len(req.values) != 1:
                raise InvalidRequestError("FC06 writes exactly one register")
            await conn.write_register(req.device_id, req.address, req.values[0])
        else:
            if len(req.values) > 123:
                raise InvalidRequestError("FC16 writes at most 123 registers")
            await conn.write_registers(req.device_id, req.address, req.values)

    # -- polling windows ---------------------------------------------------

    def _task(self, poll_id: str) -> PollTask:
        try:
            return self.polls.get(poll_id)
        except KeyError as exc:
            raise NotFoundError(f"unknown polling window {poll_id!r}") from exc

    def poll_view(self, poll_id: str) -> PollView:
        task = self._task(poll_id)
        data = self.poll_data(task, task.last_result) if task.last_result else None
        return PollView(
            definition=task.definition,
            running=task.running,
            stats=task.stats.as_dict(),
            data=data,
        )

    def list_polls(self) -> list[PollView]:
        return [self.poll_view(t.definition.id) for t in self.polls.all()]

    def _check_connection_ref(self, definition: PollDefinition) -> None:
        if definition.connection_id not in {c.id for c in self.connections.all()}:
            raise InvalidRequestError(f"unknown connection {definition.connection_id!r}")

    def add_poll(self, definition: PollDefinition) -> PollView:
        self._check_connection_ref(definition)
        try:
            self.polls.add(definition)
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        self._changed()
        return self.poll_view(definition.id)

    async def update_poll(self, definition: PollDefinition) -> PollView:
        self._task(definition.id)
        self._check_connection_ref(definition)
        await self.polls.update(definition)
        self._changed()
        return self.poll_view(definition.id)

    async def remove_poll(self, poll_id: str) -> None:
        self._task(poll_id)
        await self.polls.remove(poll_id)
        self._changed()

    @staticmethod
    def _cell_owners(d: PollDefinition) -> dict[int, int]:
        """Map every address of a window to the address of the cell that shows it.

        Mirrors ``decode_table``: a 32/64-bit value covers the registers after it.
        """
        owners: dict[int, int] = {}
        address, end = d.address, d.address + d.quantity
        while address < end:
            fmt = d.formats.get(address, d.default_format)
            count = 1 if d.function.is_bit else register_count(fmt.dtype)
            for covered in range(address, min(address + count, end)):
                owners[covered] = address
            address += count
        return owners

    async def apply_format(self, poll_id: str, patch: FormatPatch) -> PollView:
        """Set data type, byte order, scale, unit or alias on a range of cells."""
        d = self._task(poll_id).definition
        last = d.address + d.quantity - 1
        if not d.address <= patch.start <= patch.end <= last:
            raise InvalidRequestError(f"range {patch.start}-{patch.end} is outside this window")
        changes = patch.model_dump(
            exclude_none=True, include={"dtype", "order", "scale", "unit", "alias"}
        )
        if d.function.is_bit and set(changes) - {"alias"}:
            raise InvalidRequestError("coils and discrete inputs only take an alias")
        owner = self._cell_owners(d)[patch.start]
        if owner != patch.start:
            raise InvalidRequestError(
                f"address {patch.start} is part of the value at {owner}; start the range there"
            )

        formats = dict(d.formats)
        if patch.reset:
            for address in range(patch.start, patch.end + 1):
                formats.pop(address, None)
        else:
            address = patch.start
            while address <= patch.end:
                fmt = formats.get(address, d.default_format).model_copy(update=changes)
                count = 1 if d.function.is_bit else register_count(fmt.dtype)
                if address + count - 1 > last:
                    raise InvalidRequestError(
                        f"{fmt.dtype.value} at {address} needs registers up to "
                        f"{address + count - 1}, past the end of the window ({last})"
                    )
                formats[address] = fmt
                # The registers it now covers no longer start a cell of their own.
                for covered in range(address + 1, address + count):
                    formats.pop(covered, None)
                address += count
        # Entries equal to the window default add nothing; keep the workspace tidy.
        formats = {a: f for a, f in formats.items() if f != d.default_format}
        return await self.update_poll(d.model_copy(update={"formats": formats}))

    def reset_poll_stats(self, poll_id: str) -> PollView:
        self._task(poll_id).reset_stats()
        return self.poll_view(poll_id)

    def poll_data(self, task: PollTask, result: PollResult) -> PollData:
        d = task.definition
        cells: list[Cell] = []
        if result.values is not None:
            if d.function.is_bit:
                for i, bit in enumerate(result.values):
                    address = d.address + i
                    fmt = d.formats.get(address)
                    cells.append(
                        Cell(
                            address=address,
                            value=bool(bit),
                            text="1" if bit else "0",
                            raw=[int(bit)],
                            alias=fmt.alias if fmt else "",
                        )
                    )
            else:
                formats = {a: f.to_codec() for a, f in d.formats.items()}
                registers = [int(v) for v in result.values]
                for c in decode_table(registers, d.address, formats, d.default_format.to_codec()):
                    cells.append(
                        Cell(
                            address=c.address,
                            value=c.value,
                            text=c.text,
                            raw=list(c.registers) if c.covered_by is None else [c.registers[0]],
                            alias=c.fmt.alias if c.covered_by is None else "",
                            unit=c.fmt.unit if c.covered_by is None else "",
                            covered_by=c.covered_by,
                            error=c.error,
                        )
                    )
        return PollData(
            poll_id=result.poll_id,
            seq=result.seq,
            timestamp=result.timestamp,
            duration_ms=round(result.duration_ms, 2),
            ok=result.ok,
            error_kind=result.error_kind.value if result.error_kind else None,
            error=result.error,
            exception_code=result.exception_code,
            stats=result.stats,
            cells=cells,
        )

    def plan_window_write(self, poll_id: str, req: WindowWrite) -> WritePlan:
        """Work out what writing a cell sends, without sending it (for confirmation)."""
        task = self._task(poll_id)
        d = task.definition
        if not d.address <= req.address < d.address + d.quantity:
            raise InvalidRequestError("address is outside this window")
        self._check_writable(self._connection(d.connection_id))
        target: dict[str, Any] = {
            "poll_id": d.id,
            "connection_id": d.connection_id,
            "device_id": d.device_id,
            "address": req.address,
        }
        if d.function is ReadFunction.READ_COILS:
            if req.value not in (0, 1):
                raise InvalidRequestError("coil value must be 0/1 or true/false")
            on = bool(req.value)
            return WritePlan(
                **target,
                function=15 if req.force_multiple else 5,
                values=[int(on)],
                requested=on,
                result=on,
                text="1" if on else "0",
            )
        if d.function is not ReadFunction.READ_HOLDING_REGISTERS:
            raise InvalidRequestError(
                f"FC{d.function.value:02d} tables are read-only; only coils and holding "
                "registers can be written"
            )
        if isinstance(req.value, bool):
            raise InvalidRequestError("register value must be a number")
        fmt = d.formats.get(req.address, d.default_format).to_codec()
        try:
            registers = from_engineering(req.value, fmt)
            result = to_engineering(decode(registers, fmt.dtype, fmt.order), fmt)
        except CodecError as exc:
            raise InvalidRequestError(str(exc)) from exc
        if req.address + len(registers) > 0x10000:
            raise InvalidRequestError("value does not fit below address 65535")
        text = format_value(result, fmt.dtype)
        return WritePlan(
            **target,
            function=6 if len(registers) == 1 and not req.force_multiple else 16,
            values=registers,
            requested=req.value,
            result=result,
            text=text,
            # Compare as displayed: float32 noise is not rounding, 23.45 -> 23.4 is.
            rounded=text != format_value(req.value, fmt.dtype),
            unit=fmt.unit,
            dtype=fmt.dtype.value,
            order=fmt.order.value,
            scale=fmt.scale,
        )

    async def write_window(self, poll_id: str, req: WindowWrite) -> WritePlan:
        """Write a cell the way it is displayed: coils as bits, registers in engineering units."""
        plan = self.plan_window_write(poll_id, req)
        conn = self._connection(plan.connection_id)
        dev, addr, values = plan.device_id, plan.address, plan.values
        if plan.function == 5:
            await conn.write_coil(dev, addr, bool(values[0]))
        elif plan.function == 15:
            await conn.write_coils(dev, addr, [bool(v) for v in values])
        elif plan.function == 6:
            await conn.write_register(dev, addr, values[0])
        else:
            await conn.write_registers(dev, addr, values)
        return plan

    # -- traffic -----------------------------------------------------------

    @staticmethod
    def traffic_view(entry: TrafficEntry) -> TrafficEntryView:
        return TrafficEntryView(
            seq=entry.seq,
            timestamp=entry.timestamp,
            connection_id=entry.connection_id,
            direction=entry.direction.value,
            hex=entry.hex,
        )

    def list_traffic(
        self, connection_id: str | None = None, after_seq: int = 0, limit: int = 500
    ) -> list[TrafficEntryView]:
        entries = self.traffic.entries(connection_id, after_seq)
        return [self.traffic_view(e) for e in entries[-limit:]]
