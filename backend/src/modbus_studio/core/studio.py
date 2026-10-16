"""Application service: connections, polling windows and writes as one unit.

The API layer only translates HTTP/WebSocket to calls on :class:`Studio`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

import httpx

from ..models.connection import ConnectionConfig, RtuConnection, TcpConnection
from ..models.exporters import (
    ExportersConfig,
    ExportersView,
    ExporterTest,
    InfluxDBConfig,
    InfluxDBConfigView,
    InfluxDBView,
    MQTTConfig,
    MQTTConfigView,
    MQTTView,
)
from ..models.format import RegisterFormatModel
from ..models.poll import PollDefinition, ReadFunction
from ..models.views import (
    Cell,
    ConnectionView,
    FormatPatch,
    PollData,
    PollView,
    RawWrite,
    SerialPortView,
    TrafficEntryView,
    WindowWrite,
    WritePlan,
)
from ..models.workspace import Workspace
from . import influx, mqtt
from .codec import (
    CodecError,
    decode,
    decode_table,
    format_value,
    from_engineering,
    register_count,
    to_engineering,
)
from .connection import (
    ClientFactory,
    Connection,
    ConnectionManager,
    RequestError,
    default_client_factory,
)
from .frames import FrameInfo, describe
from .influx import InfluxExporter, Sample
from .mqtt import MqttExporter
from .poller import PollManager, PollResult, PollTask
from .registermap import MapError, MapRow, RegisterMapError, WindowFit, parse_register_map
from .serialports import list_serial_ports
from .traffic import TrafficEntry, TrafficLog
from .writelog import WriteLog


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
        self,
        traffic_buffer: int = 5000,
        client_factory: ClientFactory = default_client_factory,
        write_log: WriteLog | None = None,
        influx_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.traffic = TrafficLog(maxlen=traffic_buffer)
        self.write_log = write_log or WriteLog()
        self.connections = ConnectionManager(self.traffic, client_factory)
        self.polls = PollManager(self.connections)
        self.influx = InfluxExporter(influx_transport)
        self._influx_transport = influx_transport
        self.mqtt = MqttExporter()
        self.polls.subscribe(self._export)
        self._change_listeners: list[Callable[[], None]] = []

    def subscribe_changes(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` whenever connections or windows are added, edited or removed."""
        self._change_listeners.append(listener)

    def _changed(self) -> None:
        for listener in self._change_listeners:
            listener()

    def export_workspace(self, secrets: bool = True) -> Workspace:
        """The session as a workspace; ``secrets=False`` leaves out exporter secrets."""
        exporters = ExportersConfig(influxdb=self.influx.config, mqtt=self.mqtt.config)
        return Workspace(
            connections=[c.config for c in self.connections.all()],
            polls=[t.definition for t in self.polls.all()],
            exporters=exporters if secrets else exporters.without_secrets(),
        )

    async def close(self) -> None:
        await self.polls.stop_all()
        await self.connections.close_all()
        await self.influx.close()
        await self.mqtt.close()

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

    def load_workspace(self, workspace: Workspace, exporters: bool = True) -> None:
        """Add a workspace's connections and windows to the current session.

        With ``exporters`` its exporter settings replace the current ones (a merge
        keeps the session's own).
        """
        if exporters:
            self.set_influxdb(workspace.exporters.influxdb)
            self.set_mqtt(workspace.exporters.mqtt)
        for config in workspace.connections:
            self.add_connection(config)
        for definition in workspace.polls:
            self.add_poll(definition)

    async def import_workspace(self, workspace: Workspace, replace: bool) -> None:
        """Load a workspace file: replace the session, or add to it (merge).

        The workspace is fully validated by its model before anything is touched.
        """
        if replace:
            for conn in list(self.connections.all()):
                await self.remove_connection(conn.id, cascade=True)
        else:
            taken = [c.id for c in workspace.connections if c.id in self._connection_ids()]
            taken += [
                p.id for p in workspace.polls if p.id in {t.definition.id for t in self.polls.all()}
            ]
            if taken:
                raise ConflictError(
                    f"already in use: {', '.join(sorted(taken))}; import with mode=replace "
                    "or rename them in the file"
                )
        self.load_workspace(workspace, exporters=replace)

    def _connection_ids(self) -> set[str]:
        return {c.id for c in self.connections.all()}

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
        dev, addr, values = req.device_id, req.address, req.values
        send: Callable[[], Awaitable[None]]
        if req.function in (5, 15):
            if any(v not in (0, 1) for v in values):
                raise InvalidRequestError("coil values must be 0 or 1")
            bits = [bool(v) for v in values]
            if req.function == 5:
                if len(bits) != 1:
                    raise InvalidRequestError("FC05 writes exactly one coil")
                send = lambda: conn.write_coil(dev, addr, bits[0])  # noqa: E731
            else:
                send = lambda: conn.write_coils(dev, addr, bits)  # noqa: E731
        else:
            if any(not 0 <= v <= 0xFFFF for v in values):
                raise InvalidRequestError("register values must be 0..65535")
            if req.function == 6:
                if len(values) != 1:
                    raise InvalidRequestError("FC06 writes exactly one register")
                send = lambda: conn.write_register(dev, addr, values[0])  # noqa: E731
            else:
                if len(values) > 123:
                    raise InvalidRequestError("FC16 writes at most 123 registers")
                send = lambda: conn.write_registers(dev, addr, values)  # noqa: E731
        await self._logged(
            send,
            connection_id=conn.id,
            connection_name=conn.config.name,
            device_id=dev,
            function=req.function,
            address=addr,
            new=" ".join(str(v) for v in values),
            values=values,
        )

    async def _logged(self, send: Callable[[], Awaitable[None]], **entry: Any) -> None:
        """Send a write and record it, including when the device rejects it."""
        try:
            await send()
        except RequestError as exc:
            self.write_log.record(**entry, ok=False, error=str(exc))
            raise
        self.write_log.record(**entry, ok=True)

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

    async def import_register_map(self, poll_id: str, text: str, fit: bool = False) -> PollView:
        """Replace a window's per-cell formats with a CSV register map.

        With ``fit``, a window too small for the file first grows (never shrinks)
        to the smallest range that holds every row, when Modbus allows it.
        """
        d = self._task(poll_id).definition
        rows = parse_register_map(text)

        def end_of(row: MapRow) -> int:
            return row.address if d.function.is_bit else row.last_address

        last = d.address + d.quantity - 1
        window_fit: WindowFit | None = None
        if rows:
            low = min(d.address, *(r.address for r in rows))
            high = max(last, *(end_of(r) for r in rows))
            fits_modbus = high - low < d.function.max_quantity and high <= 0xFFFF
            if (low, high) != (d.address, last) and fits_modbus:
                window_fit = WindowFit(low, high - low + 1)
        if fit and window_fit:
            d = d.model_copy(
                update={"address": window_fit.address, "quantity": window_fit.quantity}
            )
            last = d.address + d.quantity - 1
            window_fit = None

        errors: list[MapError] = []
        outside = 0
        for row in rows:
            end = end_of(row)
            if not d.address <= row.address <= end <= last:
                span = f"{row.address}-{end}" if end != row.address else str(row.address)
                message = f"address {span} is outside this window ({d.address}-{last})"
                if row.address >= 30001:
                    message += "; use 0-based protocol addresses, not 3xxxx/4xxxx numbers"
                errors.append(MapError(row.line, message))
                outside += 1
            elif d.function.is_bit and (
                row.dtype != d.default_format.dtype
                or row.order != d.default_format.order
                or row.scale != 1
                or row.unit
            ):
                errors.append(MapError(row.line, "coils and discrete inputs only take an alias"))
        if errors:
            # Offer to resize only when that alone fixes the file.
            raise RegisterMapError(errors, window_fit if outside == len(errors) else None)

        if d.function.is_bit:
            formats = {r.address: RegisterFormatModel(alias=r.alias) for r in rows}
        else:
            formats = {
                r.address: RegisterFormatModel(
                    dtype=r.dtype, order=r.order, scale=r.scale, unit=r.unit, alias=r.alias
                )
                for r in rows
            }
        new = d.model_copy(update={"formats": formats})
        # Addresses missing from the file use the window default, which may be wide
        # enough to cover the next row of the file.
        owners = self._cell_owners(new)
        hidden = [
            MapError(
                r.line,
                f"address {r.address} is covered by the window's default "
                f"{d.default_format.dtype.value} at {owners[r.address]}; add a row for "
                f"{owners[r.address]} or change the window format",
            )
            for r in rows
            if owners.get(r.address, r.address) != r.address
        ]
        if hidden:
            raise RegisterMapError(hidden)
        tidy = {a: f for a, f in formats.items() if f != d.default_format}
        return await self.update_poll(d.model_copy(update={"formats": tidy}))

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

    def _displayed_text(self, task: PollTask, address: int) -> str | None:
        """Text the window shows for ``address`` after its last poll, if that poll worked."""
        result = task.last_result
        if result is None or result.values is None:
            return None
        cell = next((c for c in self.poll_data(task, result).cells if c.address == address), None)
        return None if cell is None or cell.error else cell.text

    async def write_window(self, poll_id: str, req: WindowWrite) -> WritePlan:
        """Write a cell the way it is displayed: coils as bits, registers in engineering units."""
        plan = self.plan_window_write(poll_id, req)
        task = self._task(poll_id)
        conn = self._connection(plan.connection_id)
        dev, addr, values = plan.device_id, plan.address, plan.values
        send: Callable[[], Awaitable[None]]
        if plan.function == 5:
            send = lambda: conn.write_coil(dev, addr, bool(values[0]))  # noqa: E731
        elif plan.function == 15:
            send = lambda: conn.write_coils(dev, addr, [bool(v) for v in values])  # noqa: E731
        elif plan.function == 6:
            send = lambda: conn.write_register(dev, addr, values[0])  # noqa: E731
        else:
            send = lambda: conn.write_registers(dev, addr, values)  # noqa: E731
        fmt = task.definition.formats.get(addr)
        await self._logged(
            send,
            connection_id=conn.id,
            connection_name=conn.config.name,
            device_id=dev,
            function=plan.function,
            address=addr,
            poll_id=poll_id,
            alias=fmt.alias if fmt else "",
            unit=plan.unit,
            old=self._displayed_text(task, addr),
            new=plan.text,
            values=values,
        )
        return plan

    # -- exporters -----------------------------------------------------------

    def influxdb_view(self) -> InfluxDBView:
        return InfluxDBView(
            config=InfluxDBConfigView.of(self.influx.config),
            status=self.influx.status.model_copy(),
        )

    def exporters_view(self) -> ExportersView:
        return ExportersView(influxdb=self.influxdb_view(), mqtt=self.mqtt_view())

    def _with_token(self, config: InfluxDBConfig) -> InfluxDBConfig:
        """A missing token means the current one; an empty string means none."""
        if config.token is None:
            return config.model_copy(update={"token": self.influx.config.token})
        if config.token == "":
            return config.model_copy(update={"token": None})
        return config

    def _with_password(self, config: MQTTConfig) -> MQTTConfig:
        """A missing password means the current one; an empty string means none."""
        if config.password is None:
            return config.model_copy(update={"password": self.mqtt.config.password})
        if config.password == "":
            return config.model_copy(update={"password": None})
        return config

    def set_influxdb(self, config: InfluxDBConfig) -> InfluxDBView:
        """Apply InfluxDB settings. A missing token keeps the current one; an empty
        string removes it."""
        self.influx.configure(self._with_token(config))
        self._changed()
        return self.influxdb_view()

    def mqtt_view(self) -> MQTTView:
        return MQTTView(
            config=MQTTConfigView.of(self.mqtt.config),
            status=self.mqtt.status.model_copy(),
        )

    def set_mqtt(self, config: MQTTConfig) -> MQTTView:
        """Apply MQTT settings. A missing password keeps the current one; an empty
        string removes it."""
        self.mqtt.configure(self._with_password(config))
        self._changed()
        return self.mqtt_view()

    async def test_influxdb(self, config: InfluxDBConfig) -> ExporterTest:
        """Try InfluxDB settings without applying them (token as in ``set_influxdb``)."""
        return await influx.test_connection(self._with_token(config), self._influx_transport)

    async def test_mqtt(self, config: MQTTConfig) -> ExporterTest:
        """Try MQTT settings without applying them (password as in ``set_mqtt``)."""
        config = self._with_password(config)
        # Its own client ID: reusing the exporter's would make the broker drop it.
        client_id = f"{config.client_id or self.mqtt.default_client_id}-test"
        return await asyncio.to_thread(mqtt.test_connection, config, client_id)

    def _export(self, result: PollResult) -> None:
        """Hand a poll result to the exporters. Runs inside the poll loop: no I/O."""
        if not (self.influx.active or self.mqtt.active) or result.values is None:
            return
        try:
            task = self.polls.get(result.poll_id)
            conn = self.connections.get(task.definition.connection_id)
        except KeyError:  # removed while the request was in flight
            return
        d = task.definition
        samples = [
            Sample(
                window=d.name or d.id,
                connection=conn.config.name or conn.id,
                device=d.device_id,
                address=cell.address,
                alias=cell.alias,
                unit=cell.unit,
                value=cell.value,
                timestamp=result.timestamp,
            )
            for cell in self.poll_data(task, result).cells
            if cell.value is not None and cell.covered_by is None and cell.error is None
        ]
        self.influx.offer(samples)
        self.mqtt.offer(samples)

    # -- serial ports --------------------------------------------------------

    async def serial_ports(self) -> list[SerialPortView]:
        ports = await asyncio.to_thread(list_serial_ports)
        rtu = [c.config for c in self.connections.all() if isinstance(c.config, RtuConnection)]
        return [
            SerialPortView(
                **asdict(p),
                used_by=[c.id for c in rtu if c.serial_port in (p.device, p.stable_path)],
            )
            for p in ports
        ]

    # -- traffic -----------------------------------------------------------

    def traffic_view(self, entry: TrafficEntry) -> TrafficEntryView:
        info = FrameInfo()
        try:
            config = self.connections.get(entry.connection_id).config
        except KeyError:  # the connection was removed; its frames stay in the log
            pass
        else:
            info = describe(entry.data, "tcp" if isinstance(config, TcpConnection) else "rtu")
        return TrafficEntryView(
            seq=entry.seq,
            timestamp=entry.timestamp,
            connection_id=entry.connection_id,
            direction=entry.direction.value,
            hex=entry.hex,
            device_id=info.device_id,
            function=info.function,
            exception_code=info.exception_code,
            transaction_id=info.transaction_id,
            error=info.error,
        )

    def list_traffic(
        self, connection_id: str | None = None, after_seq: int = 0, limit: int = 500
    ) -> list[TrafficEntryView]:
        entries = self.traffic.entries(connection_id, after_seq)
        return [self.traffic_view(e) for e in entries[-limit:]]
