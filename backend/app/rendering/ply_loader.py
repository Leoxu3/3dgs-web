"""Small scene description helper for configured PLY paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def describe_ply(scene_ply_path: str) -> dict[str, Any]:
    if not scene_ply_path:
        return {
            "path": None,
            "exists": False,
            "is_file": False,
            "is_ply": False,
            "name": None,
            "size_bytes": None,
            "message": "SCENE_PLY_PATH is not set",
        }

    path = Path(scene_ply_path).expanduser()
    exists = path.exists()
    is_file = path.is_file()
    is_ply = path.suffix.lower() == ".ply"
    message = "ready" if exists and is_file and is_ply else "Scene path is not ready"
    return {
        "path": str(path),
        "exists": exists,
        "is_file": is_file,
        "is_ply": is_ply,
        "name": path.name,
        "size_bytes": path.stat().st_size if exists and is_file else None,
        "message": message,
    }
