"""HTTP API routes for the Web viewer skeleton."""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.config import Settings
from backend.app.rendering.camera import RenderRequest
from backend.app.rendering.renderer import Renderer
from backend.app.refinement.base import RefinementResult
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
    refine_lock = threading.Lock()

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
            "refiner_backend": settings.refiner_backend,
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
            "refiner_backend": settings.refiner_backend,
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
            "refiner_backend": settings.refiner_backend,
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
            "refiner_backend": settings.refiner_backend,
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
            _refine_when_available,
            refine_lock,
            refiner,
            request.image_data_url,
            request.camera,
        )
        return result.to_dict()

    @router.post("/refine-view")
    async def refine_view(request: RenderRequest) -> dict[str, Any]:
        total_start = time.perf_counter()

        render_start = time.perf_counter()
        raw = await run_in_threadpool(
            renderer.render,
            camera=request.camera,
            width=request.width,
            height=request.height,
            quality=request.quality,
        )
        render_wall_ms = _elapsed_ms(render_start)

        camera_payload = request.camera.model_dump()
        refine_start = time.perf_counter()
        refined: RefinementResult = await run_in_threadpool(
            _refine_when_available,
            refine_lock,
            refiner,
            raw.image_data_url,
            camera_payload,
        )
        refine_wall_ms = _elapsed_ms(refine_start)

        return {
            "raw": raw.to_dict(),
            "refined": refined.to_dict(),
            "timings_ms": {
                "render_wall_ms": round(render_wall_ms, 2),
                "refine_wall_ms": round(refine_wall_ms, 2),
                "total_wall_ms": round(_elapsed_ms(total_start), 2),
            },
        }

    return router


def _refine_when_available(
    refine_lock: threading.Lock,
    refiner: Any,
    image_data_url: str,
    camera: dict[str, Any] | None,
) -> RefinementResult:
    acquired = refine_lock.acquire(blocking=False)
    if not acquired:
        return RefinementResult(
            image_data_url=image_data_url,
            latency_ms=0.0,
            refiner=refiner.name,
            status="busy",
            message="Another refinement is still running; retry shortly",
            fallback_mode=False,
            timings_ms={"busy_wait_ms": 0.0},
        )

    try:
        return refiner.refine(image_data_url, camera)
    finally:
        refine_lock.release()


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000
