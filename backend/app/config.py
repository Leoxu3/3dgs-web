"""Application configuration for headless-server deployment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = Path(__file__).resolve().parent


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    service_name: str = "3DGS Interactive Viewer"
    host: str = field(default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("APP_PORT", "8000")))
    scene_ply_path: str = field(default_factory=lambda: os.getenv("SCENE_PLY_PATH", ""))
    renderer_backend: str = field(default_factory=lambda: os.getenv("RENDERER_BACKEND", "auto"))
    gsplat_device: str = field(default_factory=lambda: os.getenv("GSPLAT_DEVICE", "cuda"))
    refiner_backend: str = field(default_factory=lambda: os.getenv("REFINER_BACKEND", "auto"))
    difix3d_variant: str = field(default_factory=lambda: os.getenv("DIFIX3D_VARIANT", ""))
    difix3d_command: str = field(default_factory=lambda: os.getenv("DIFIX3D_COMMAND", ""))
    difix3d_worker_command: str = field(
        default_factory=lambda: os.getenv("DIFIX3D_WORKER_COMMAND", "")
    )
    difix3d_python_callable: str = field(
        default_factory=lambda: os.getenv("DIFIX3D_PYTHON_CALLABLE", "")
    )
    difix3d_timeout_seconds: float = field(
        default_factory=lambda: _float_env("DIFIX3D_TIMEOUT_SECONDS", 120.0)
    )
    static_dir: Path = APP_ROOT / "static"
    project_root: Path = PROJECT_ROOT


def get_settings() -> Settings:
    return Settings()
