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
            "vertical_axis": None,
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
        "vertical_axis": read_vertical_axis(path) if exists and is_file and is_ply else None,
        "message": message,
    }


def read_vertical_axis(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            for _index in range(256):
                line = handle.readline()
                if not line:
                    return None
                text = line.decode("ascii", errors="replace").strip()
                if text == "end_header":
                    return None
                prefix = "comment Vertical Axis:"
                if text.startswith(prefix):
                    axis = text[len(prefix) :].strip().lower()
                    return axis if axis in {"x", "y", "z"} else None
    except OSError:
        return None
    return None
