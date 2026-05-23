"""Camera and render request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CameraState(BaseModel):
    yaw: float = 0.0
    pitch: float = 0.0
    distance: float = 3.0
    target: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    fov: float = 45.0


class RenderRequest(BaseModel):
    camera: CameraState = Field(default_factory=CameraState)
    width: int = Field(default=960, ge=64, le=4096)
    height: int = Field(default=540, ge=64, le=4096)
    quality: Literal["interactive", "idle"] = "interactive"
