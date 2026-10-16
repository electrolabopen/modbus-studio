"""REST API. Every change made here is also pushed to WebSocket clients.

Handlers are ``async def`` on purpose: FastAPI runs plain ``def`` handlers in a
thread pool, and pymodbus clients and poll tasks must be created on the event loop.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, status
from fastapi.responses import JSONResponse

from ..core.connection import RequestError
from ..core.registermap import RegisterMapError
from ..core.studio import (
    ConflictError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
    Studio,
)
from ..models.connection import ConnectionConfig
from ..models.exporters import (
    ExportersView,
    ExporterTest,
    InfluxDBConfig,
    InfluxDBView,
    MQTTConfig,
    MQTTView,
)
from ..models.poll import PollDefinition
from ..models.views import (
    ConnectionView,
    FormatPatch,
    PollData,
    PollView,
    RawWrite,
    RegisterMapImport,
    SerialPortView,
    TrafficEntryView,
    WindowWrite,
    WorkspaceImportResult,
    WriteLogEntry,
    WritePlan,
)
from ..models.workspace import Workspace
from .auth import require_token
from .ws import Hub


def get_studio(request: Request) -> Studio:
    studio: Studio = request.app.state.studio
    return studio


def get_hub(request: Request) -> Hub:
    hub: Hub = request.app.state.hub
    return hub


StudioDep = Annotated[Studio, Depends(get_studio)]
HubDep = Annotated[Hub, Depends(get_hub)]

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


# -- connections --------------------------------------------------------------


@router.get("/connections", tags=["connections"])
async def list_connections(studio: StudioDep) -> list[ConnectionView]:
    return studio.list_connections()


@router.get(
    "/serial-ports",
    tags=["connections"],
    summary="List the serial ports of the machine running the server",
    description="For RTU connections. `stable_path` is the /dev/serial/by-id link of a USB "
    "adapter on Linux, which keeps working when adapters are plugged in another order. "
    "Inside Docker only the devices passed with --device are listed.",
)
async def list_serial_ports(studio: StudioDep) -> list[SerialPortView]:
    return await studio.serial_ports()


@router.post("/connections", status_code=status.HTTP_201_CREATED, tags=["connections"])
async def create_connection(
    config: ConnectionConfig, studio: StudioDep, hub: HubDep
) -> ConnectionView:
    view = studio.add_connection(config)
    hub.publish_snapshot()
    return view


@router.get("/connections/{connection_id}", tags=["connections"])
async def get_connection(connection_id: str, studio: StudioDep) -> ConnectionView:
    return studio.connection_view(connection_id)


@router.put("/connections/{connection_id}", tags=["connections"])
async def update_connection(
    connection_id: str, config: ConnectionConfig, studio: StudioDep, hub: HubDep
) -> ConnectionView:
    view = await studio.update_connection(config.model_copy(update={"id": connection_id}))
    hub.publish_snapshot()
    return view


@router.delete(
    "/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["connections"]
)
async def delete_connection(
    connection_id: str,
    studio: StudioDep,
    hub: HubDep,
    cascade: Annotated[bool, Query(description="Also delete the windows using it")] = False,
) -> Response:
    await studio.remove_connection(connection_id, cascade=cascade)
    hub.publish_snapshot()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/connections/{connection_id}/write",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["connections"],
    summary="Raw write with FC05, FC06, FC15 or FC16",
)
async def raw_write(connection_id: str, req: RawWrite, studio: StudioDep) -> Response:
    await studio.write_raw(connection_id, req)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- polling windows ----------------------------------------------------------


@router.get("/polls", tags=["polls"])
async def list_polls(studio: StudioDep) -> list[PollView]:
    return studio.list_polls()


@router.post("/polls", status_code=status.HTTP_201_CREATED, tags=["polls"])
async def create_poll(definition: PollDefinition, studio: StudioDep, hub: HubDep) -> PollView:
    view = studio.add_poll(definition)
    hub.publish_snapshot()
    return view


@router.get("/polls/{poll_id}", tags=["polls"])
async def get_poll(poll_id: str, studio: StudioDep) -> PollView:
    return studio.poll_view(poll_id)


@router.put("/polls/{poll_id}", tags=["polls"])
async def update_poll(
    poll_id: str, definition: PollDefinition, studio: StudioDep, hub: HubDep
) -> PollView:
    view = await studio.update_poll(definition.model_copy(update={"id": poll_id}))
    hub.publish_snapshot()
    return view


@router.delete("/polls/{poll_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["polls"])
async def delete_poll(poll_id: str, studio: StudioDep, hub: HubDep) -> Response:
    await studio.remove_poll(poll_id)
    hub.publish_snapshot()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/polls/{poll_id}/data", tags=["polls"])
async def get_poll_data(poll_id: str, studio: StudioDep) -> PollData | None:
    return studio.poll_view(poll_id).data


@router.post("/polls/{poll_id}/reset", tags=["polls"], summary="Reset Tx/Err counters")
async def reset_poll(poll_id: str, studio: StudioDep, hub: HubDep) -> PollView:
    view = studio.reset_poll_stats(poll_id)
    hub.publish_snapshot()
    return view


@router.patch(
    "/polls/{poll_id}/formats",
    tags=["polls"],
    summary="Set data type, byte order, scale, unit or alias on a range of cells",
)
async def patch_formats(
    poll_id: str, patch: FormatPatch, studio: StudioDep, hub: HubDep
) -> PollView:
    view = await studio.apply_format(poll_id, patch)
    hub.publish_snapshot()
    return view


@router.post(
    "/polls/{poll_id}/write/preview",
    tags=["polls"],
    summary="Show what writing a cell would send, without writing",
)
async def window_write_preview(poll_id: str, req: WindowWrite, studio: StudioDep) -> WritePlan:
    return studio.plan_window_write(poll_id, req)


@router.post(
    "/polls/{poll_id}/write",
    tags=["polls"],
    summary="Write a cell in engineering units using the window's format",
)
async def window_write(poll_id: str, req: WindowWrite, studio: StudioDep) -> WritePlan:
    return await studio.write_window(poll_id, req)


# -- traffic ------------------------------------------------------------------


@router.get("/traffic", tags=["traffic"])
async def list_traffic(
    studio: StudioDep,
    connection_id: str | None = None,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[TrafficEntryView]:
    return studio.list_traffic(connection_id, after_seq, limit)


@router.delete("/traffic", status_code=status.HTTP_204_NO_CONTENT, tags=["traffic"])
async def clear_traffic(studio: StudioDep) -> Response:
    studio.traffic.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- register maps, workspace, write log ----------------------------------------


@router.post(
    "/polls/{poll_id}/register-map",
    tags=["polls"],
    summary="Replace a window's cell formats with a CSV register map",
    description="Columns: address, alias, type, byte_order, scale, unit. Nothing is "
    "applied unless every row is valid; problems are listed per line in `errors`. When "
    "the only problem is rows outside the window and a larger window would hold them, "
    "the error also has `fit` (address, quantity); `fit=true` grows the window to it "
    "and applies the map in one step.",
)
async def import_register_map(
    poll_id: str,
    body: RegisterMapImport,
    studio: StudioDep,
    hub: HubDep,
    fit: Annotated[bool, Query(description="Grow the window to hold every row")] = False,
) -> PollView:
    view = await studio.import_register_map(poll_id, body.csv, fit=fit)
    hub.publish_snapshot()
    return view


@router.get(
    "/workspace",
    tags=["workspace"],
    summary="Export connections, windows and exporter settings",
    description="Exporter tokens are left out; importing the file keeps the current ones.",
)
async def export_workspace(studio: StudioDep) -> Workspace:
    return studio.export_workspace(secrets=False)


@router.get("/exporters", tags=["exporters"], summary="Settings and status of every exporter")
async def get_exporters(studio: StudioDep) -> ExportersView:
    return studio.exporters_view()


@router.post(
    "/exporters/influxdb/test",
    tags=["exporters"],
    summary="Try InfluxDB settings without saving them",
    description="An empty write to the bucket: checks the URL, the token, the org and the "
    "bucket, and stores nothing. A missing `token` means the saved one.",
)
async def test_influxdb(config: InfluxDBConfig, studio: StudioDep) -> ExporterTest:
    return await studio.test_influxdb(config)


@router.post(
    "/exporters/mqtt/test",
    tags=["exporters"],
    summary="Try MQTT settings without saving them",
    description="Connects to the broker once, with its own client ID, and disconnects. "
    "A missing `password` means the saved one.",
)
async def test_mqtt(config: MQTTConfig, studio: StudioDep) -> ExporterTest:
    return await studio.test_mqtt(config)


@router.get("/exporters/influxdb", tags=["exporters"], summary="InfluxDB exporter settings")
async def get_influxdb(studio: StudioDep) -> InfluxDBView:
    """The settings (without the token) and the export status: state, last error,
    points sent, writes, errors, dropped and pending points."""
    return studio.influxdb_view()


@router.put(
    "/exporters/influxdb",
    tags=["exporters"],
    summary="Change the InfluxDB exporter settings",
    description="Omit `token` (or send null) to keep the current token; send an empty "
    "string to remove it. Applied at once and saved with the workspace.",
)
async def put_influxdb(config: InfluxDBConfig, studio: StudioDep) -> InfluxDBView:
    return studio.set_influxdb(config)


@router.get("/exporters/mqtt", tags=["exporters"], summary="MQTT exporter settings")
async def get_mqtt(studio: StudioDep) -> MQTTView:
    """The settings (without the password) and the status: connected, state, last
    error, messages sent, errors, dropped and pending messages."""
    return studio.mqtt_view()


@router.put(
    "/exporters/mqtt",
    tags=["exporters"],
    summary="Change the MQTT exporter settings",
    description="Omit `password` (or send null) to keep the current password; send an "
    "empty string to remove it. Applied at once (the client reconnects) and saved with "
    "the workspace.",
)
async def put_mqtt(config: MQTTConfig, studio: StudioDep) -> MQTTView:
    return studio.set_mqtt(config)


@router.post("/workspace", tags=["workspace"], summary="Import a workspace file")
async def import_workspace(
    workspace: Workspace,
    studio: StudioDep,
    hub: HubDep,
    mode: Annotated[
        Literal["replace", "merge"],
        Query(description="replace: drop the current session first; merge: add to it"),
    ] = "replace",
) -> WorkspaceImportResult:
    await studio.import_workspace(workspace, replace=mode == "replace")
    hub.publish_snapshot()
    return WorkspaceImportResult(connections=len(workspace.connections), polls=len(workspace.polls))


@router.get("/writes", tags=["writes"], summary="Write log, newest first")
async def list_writes(
    studio: StudioDep, limit: Annotated[int, Query(ge=1, le=500)] = 200
) -> list[WriteLogEntry]:
    return studio.write_log.entries(limit)


# -- error mapping ------------------------------------------------------------


def install_error_handlers(app: FastAPI) -> None:
    def detail(code: int, message: str) -> JSONResponse:
        return JSONResponse(status_code=code, content={"detail": message})

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return detail(status.HTTP_404_NOT_FOUND, str(exc))

    @app.exception_handler(ConflictError)
    async def _conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return detail(status.HTTP_409_CONFLICT, str(exc))

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_: Request, exc: ForbiddenError) -> JSONResponse:
        return detail(status.HTTP_403_FORBIDDEN, str(exc))

    @app.exception_handler(InvalidRequestError)
    async def _invalid(_: Request, exc: InvalidRequestError) -> JSONResponse:
        return detail(status.HTTP_400_BAD_REQUEST, str(exc))

    @app.exception_handler(RegisterMapError)
    async def _register_map(_: Request, exc: RegisterMapError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": str(exc),
                "errors": [{"line": e.line, "message": e.message} for e in exc.errors],
                "fit": exc.fit and {"address": exc.fit.address, "quantity": exc.fit.quantity},
            },
        )

    @app.exception_handler(RequestError)
    async def _modbus(_: Request, exc: RequestError) -> JSONResponse:
        # The device or the link failed, not the HTTP request: 502 Bad Gateway.
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "detail": str(exc),
                "kind": exc.kind.value,
                "exception_code": exc.exception_code,
            },
        )
