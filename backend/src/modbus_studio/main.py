from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import rest, ws
from .api.auth import require_token
from .config import Settings, get_settings
from .core.persistence import AutoSaver, StateFile
from .core.studio import Studio
from .core.writelog import WriteLog
from .models.workspace import Workspace

log = logging.getLogger("modbus_studio")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.dependency_overrides.get(get_settings, get_settings)()
    # Frames are captured by the traffic monitor; pymodbus' own frame logging is just noise.
    logging.getLogger("pymodbus").setLevel(logging.ERROR)
    studio = Studio(
        traffic_buffer=settings.traffic_buffer,
        write_log=WriteLog(settings.write_log_file),
    )
    state = StateFile(settings.state_file) if settings.state_file else None
    restored = state.load() if state else None
    if restored is not None:
        studio.load_workspace(restored)
        log.info("restored workspace from %s", settings.state_file)
    elif settings.workspace is not None:
        # A broken workspace file stops the server: silently starting empty would hide it.
        studio.load_workspace(Workspace.load(settings.workspace))
        log.info("loaded workspace %s", settings.workspace)
    saver = None
    if state is not None:
        saver = AutoSaver(state, studio.export_workspace)
        saver.flush()  # from now on the state file exists and is the source of truth
        studio.subscribe_changes(saver.schedule)
    app.state.studio = studio
    app.state.hub = ws.Hub(studio)
    yield
    app.state.hub.close()
    if saver is not None:
        saver.flush()
    await studio.close()


def create_app() -> FastAPI:
    app = FastAPI(title="modbus-studio", version=__version__, lifespan=lifespan)

    public = APIRouter(prefix="/api")

    @public.get("/health")
    def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
        return {"status": "ok", "version": __version__, "auth": bool(settings.token)}

    protected = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @protected.get("/info")
    def info(request: Request) -> dict[str, object]:
        studio: Studio = request.app.state.studio
        return {
            "version": __version__,
            "connections": len(studio.connections.all()),
            "polls": len(studio.polls.all()),
        }

    app.include_router(public)
    app.include_router(protected)
    app.include_router(rest.router)
    app.include_router(ws.router)
    rest.install_error_handlers(app)

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
    return app


app = create_app()


def run(argv: list[str] | None = None) -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(
        prog="modbus-studio",
        description="Open-source Modbus master in the browser. Settings come from "
        "MODBUS_STUDIO_* environment variables: HOST (default 127.0.0.1), PORT (8000), "
        "TOKEN, STATE_FILE, WORKSPACE, WRITE_LOG_FILE, TRAFFIC_BUFFER. "
        "See https://github.com/electrolabopen/modbus-studio",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)

    settings = get_settings()
    # uvicorn only configures its own loggers; without this our INFO messages are dropped.
    logging.basicConfig(level=settings.log_level.upper(), format="%(levelname)s:     %(message)s")
    if not settings.is_loopback and not settings.token:
        log.warning(
            "Listening on %s without MODBUS_STUDIO_TOKEN: anyone on the network can "
            "read and write your devices.",
            settings.host,
        )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    run()
