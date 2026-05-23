"""Renderer abstraction shared by concrete rendering backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from backend.app.rendering.camera import CameraState


RenderQuality = Literal["interactive", "idle"]


@dataclass(frozen=True)
class RenderResult:
    image_data_url: str
    width: int
    height: int
    render_ms: float
    renderer: str
    quality: RenderQuality

    def to_dict(self) -> dict[str, object]:
        return {
            "image_data_url": self.image_data_url,
            "width": self.width,
            "height": self.height,
            "render_ms": round(self.render_ms, 2),
            "renderer": self.renderer,
            "quality": self.quality,
        }


class Renderer(Protocol):
    name: str
    scene_ply_path: str

    def set_scene_ply_path(self, scene_ply_path: str) -> None:
        """Switch the renderer to a different scene file."""
        raise NotImplementedError

    def render(
        self,
        camera: CameraState,
        width: int,
        height: int,
        quality: RenderQuality,
    ) -> RenderResult:
        """Render one camera view into a browser-displayable image."""
        raise NotImplementedError
