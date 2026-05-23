"""HTTP API routes for the Web viewer skeleton."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.config import Settings
from backend.app.rendering.camera import RenderRequest
from backend.app.rendering.renderer import Renderer
from backend.app.refinement.fallback import RefinementResult
from backend.app.scene import SceneManager, ScenePathError


class RefineRequest(BaseModel):
    image_data_url: str
    camera: dict[str, Any] | None = None


class ScenePathRequest(BaseModel):
    path: str = Field(default="", max_length=4096)


def create_api_router(
    settings: Settings,
    scene_manager: SceneManager,
    renderer: Renderer,
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
            "renderer_backend": settings.renderer_backend,
            "refiner": refiner.name,
            "fallback_mode": refiner.is_fallback,
            "scene": scene_manager.describe_current(),
        }

    @router.get("/scene")
    async def scene() -> dict[str, Any]:
        return {
            "scene": scene_manager.describe_current(),
            "renderer": renderer.name,
            "renderer_backend": settings.renderer_backend,
            "refiner": refiner.name,
            "fallback_mode": refiner.is_fallback,
        }

    @router.get("/scenes")
    async def scenes() -> dict[str, Any]:
        return {
            "scenes": scene_manager.list_scene_candidates(),
            "data_dir": str(scene_manager.data_dir),
        }

    @router.post("/scene")
    async def set_scene(request: ScenePathRequest) -> dict[str, Any]:
        try:
            scene_description = scene_manager.set_scene_ply_path(request.path)
        except ScenePathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        renderer.set_scene_ply_path(scene_manager.scene_ply_path)
        return {
            "scene": scene_description,
            "renderer": renderer.name,
            "refiner": refiner.name,
            "fallback_mode": refiner.is_fallback,
        }

    @router.delete("/scene")
    async def clear_scene() -> dict[str, Any]:
        scene_description = scene_manager.clear_scene_ply_path()
        renderer.set_scene_ply_path("")
        return {
            "scene": scene_description,
            "renderer": renderer.name,
            "refiner": refiner.name,
            "fallback_mode": refiner.is_fallback,
        }

    @router.post("/render")
    async def render(request: RenderRequest) -> dict[str, Any]:
        result = await run_in_threadpool(
            renderer.render,
            camera=request.camera,
            width=request.width,
            height=request.height,
            quality=request.quality,
        )
        return result.to_dict()

    @router.post("/refine")
    async def refine(request: RefineRequest) -> dict[str, Any]:
        result: RefinementResult = await run_in_threadpool(
            refiner.refine,
            request.image_data_url,
        )
        return result.to_dict()

    return router
