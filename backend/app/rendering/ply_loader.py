"""Small scene description helper for configured PLY paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def describe_ply(scene_ply_path: str) -> dict[str, Any]:
    if not scene_ply_path:
        return {
            "path": None,
            "exists": False,
            "message": "SCENE_PLY_PATH is not set",
        }

    path = Path(scene_ply_path).expanduser()
    return {
        "path": str(path),
        "exists": path.exists(),
        "name": path.name,
        "size_bytes": path.stat().st_size if path.exists() else None,
    }
