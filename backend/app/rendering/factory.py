"""Renderer construction entrypoint.

This keeps the application wired to the renderer abstraction while the concrete
implementation remains the mock SVG renderer.
"""

from __future__ import annotations

from backend.app.rendering.mock import MockRenderer
from backend.app.rendering.renderer import Renderer


def create_renderer(scene_ply_path: str = "") -> Renderer:
    return MockRenderer(scene_ply_path=scene_ply_path)
