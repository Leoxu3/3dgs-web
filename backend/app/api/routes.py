"""HTTP API routes for the Web viewer skeleton."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.rendering.camera import RenderRequest
from backend.app.rendering.ply_loader import describe_ply
from backend.app.rendering.renderer import StubRenderer
from backend.app.refinement.fallback import RefinementResult


class RefineRequest(BaseModel):
    image_data_url: str
    camera: dict[str, Any] | None = None


def create_api_router(
    settings: Settings,
    renderer: StubRenderer,
    refiner: Any,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "headless_server_friendly": True,
            "desktop_gui_required": False,
            "renderer": renderer.name,
            "refiner": refiner.name,
            "fallback_mode": refiner.is_fallback,
        }

    @router.get("/scene")
    async def scene() -> dict[str, Any]:
        return {
            "scene": describe_ply(settings.scene_ply_path),
            "renderer": renderer.name,
            "refiner": refiner.name,
            "fallback_mode": refiner.is_fallback,
        }

    @router.post("/render")
    async def render(request: RenderRequest) -> dict[str, Any]:
        result = renderer.render(
            camera=request.camera,
            width=request.width,
            height=request.height,
            quality=request.quality,
        )
        return result.to_dict()

    @router.post("/refine")
    async def refine(request: RefineRequest) -> dict[str, Any]:
        result: RefinementResult = refiner.refine(request.image_data_url)
        return result.to_dict()

    return router
