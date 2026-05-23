"""Application configuration for headless-server deployment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    service_name: str = "3DGS Web Viewer Skeleton"
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = int(os.getenv("APP_PORT", "8000"))
    scene_ply_path: str = os.getenv("SCENE_PLY_PATH", "")
    static_dir: Path = APP_ROOT / "static"
    project_root: Path = PROJECT_ROOT


def get_settings() -> Settings:
    return Settings()
