"""FastAPI entrypoint for the server-friendly Web viewer."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import create_api_router
from backend.app.api.websocket import router as websocket_router
from backend.app.config import get_settings
from backend.app.refinement.difix import create_refiner
from backend.app.rendering.renderer import StubRenderer


def create_app() -> FastAPI:
    settings = get_settings()
    renderer = StubRenderer(scene_ply_path=settings.scene_ply_path)
    refiner = create_refiner()

    app = FastAPI(
        title=settings.service_name,
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    app.state.settings = settings
    app.state.renderer = renderer
    app.state.refiner = refiner

    app.include_router(
        create_api_router(settings=settings, renderer=renderer, refiner=refiner),
        prefix="/api",
    )
    app.include_router(websocket_router, prefix="/api")
    app.mount(
        "/static",
        StaticFiles(directory=str(settings.static_dir)),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(settings.static_dir / "index.html")

    return app


app = create_app()
