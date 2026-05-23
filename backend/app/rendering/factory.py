"""Renderer construction entrypoint."""

from __future__ import annotations

import logging

from backend.app.rendering.gsplat_renderer import GsplatRenderer, GsplatUnavailable
from backend.app.rendering.mock import MockRenderer
from backend.app.rendering.renderer import Renderer


LOGGER = logging.getLogger(__name__)


def create_renderer(
    scene_ply_path: str = "",
    renderer_backend: str = "auto",
    gsplat_device: str = "cuda",
) -> Renderer:
    backend = renderer_backend.strip().lower()
    if backend == "mock":
        return MockRenderer(scene_ply_path=scene_ply_path)

    if backend not in {"auto", "gsplat"}:
        reason = f"unknown renderer backend '{renderer_backend}', using MockRenderer"
        LOGGER.warning(reason)
        return MockRenderer(scene_ply_path=scene_ply_path, fallback_reason=reason)

    try:
        return _create_gsplat_renderer(
            scene_ply_path=scene_ply_path,
            gsplat_device=gsplat_device,
        )
    except GsplatUnavailable as exc:
        reason = f"gsplat unavailable: {exc}"
        LOGGER.info(reason)
        return MockRenderer(scene_ply_path=scene_ply_path, fallback_reason=reason)


def _create_gsplat_renderer(scene_ply_path: str, gsplat_device: str) -> Renderer:
    return GsplatRenderer(scene_ply_path=scene_ply_path, device=gsplat_device)
