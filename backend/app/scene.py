"""Runtime scene / PLY path state management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from backend.app.rendering.ply_loader import describe_ply


class ScenePathError(ValueError):
    """Raised when a requested scene path cannot be used."""


@dataclass(frozen=True)
class ScenePath:
    original: str
    resolved: Path


class SceneManager:
    """Keeps track of the selected PLY file without requiring server restart."""

    def __init__(self, project_root: Path, scene_ply_path: str = "") -> None:
        self.project_root = project_root.resolve()
        self.data_dir = self.project_root / "data"
        self._lock = RLock()
        self._scene_path = self._normalize_initial_path(scene_ply_path)

    @property
    def scene_ply_path(self) -> str:
        with self._lock:
            return str(self._scene_path.resolved) if self._scene_path else ""

    def describe_current(self) -> dict[str, Any]:
        with self._lock:
            path = self.scene_ply_path
        return self._with_project_relative(describe_ply(path))

    def set_scene_ply_path(self, raw_path: str) -> dict[str, Any]:
        requested = raw_path.strip()
        if not requested:
            return self.clear_scene_ply_path()

        scene_path = self._normalize_path(requested)
        self._validate_scene_path(scene_path.resolved)

        with self._lock:
            self._scene_path = scene_path

        return self.describe_current()

    def clear_scene_ply_path(self) -> dict[str, Any]:
        with self._lock:
            self._scene_path = None
        return self.describe_current()

    def list_scene_candidates(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.data_dir.exists():
            return []

        candidates = sorted(
            (
                path
                for path in self.data_dir.rglob("*")
                if path.is_file() and path.suffix.lower() == ".ply"
            ),
            key=lambda path: str(path.relative_to(self.project_root)),
        )
        return [
            self._with_project_relative(describe_ply(str(path)))
            for path in candidates[:limit]
        ]

    def _normalize_initial_path(self, raw_path: str) -> ScenePath | None:
        requested = raw_path.strip()
        if not requested:
            return None
        return self._normalize_path(requested)

    def _normalize_path(self, raw_path: str) -> ScenePath:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.project_root / path
        return ScenePath(original=raw_path, resolved=path.resolve(strict=False))

    def _validate_scene_path(self, path: Path) -> None:
        if path.suffix.lower() != ".ply":
            raise ScenePathError("Scene path must point to a .ply file")
        if not path.exists():
            raise ScenePathError("Scene PLY path does not exist")
        if not path.is_file():
            raise ScenePathError("Scene PLY path is not a file")

    def _with_project_relative(self, description: dict[str, Any]) -> dict[str, Any]:
        path_text = description.get("path")
        if not path_text:
            return {
                **description,
                "relative_path": None,
                "data_dir": str(self.data_dir),
            }

        try:
            relative_path = str(Path(path_text).resolve(strict=False).relative_to(self.project_root))
        except ValueError:
            relative_path = None

        return {
            **description,
            "relative_path": relative_path,
            "data_dir": str(self.data_dir),
        }
