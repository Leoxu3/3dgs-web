"""Shared refinement interfaces and result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RefinementResult:
    image_data_url: str
    latency_ms: float
    refiner: str
    status: str
    message: str
    fallback_mode: bool
    timings_ms: dict[str, float] | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "image_data_url": self.image_data_url,
            "latency_ms": round(self.latency_ms, 2),
            "refiner": self.refiner,
            "status": self.status,
            "message": self.message,
            "fallback_mode": self.fallback_mode,
        }
        if self.timings_ms is not None:
            data["timings_ms"] = {
                name: round(value, 2) for name, value in self.timings_ms.items()
            }
        return data


class Refiner(Protocol):
    name: str
    is_fallback: bool

    def refine(
        self,
        image_data_url: str,
        camera: dict[str, Any] | None = None,
    ) -> RefinementResult:
        """Refine one rendered frame and return a browser-displayable image."""
        ...


class RefinerUnavailable(RuntimeError):
    """Raised when a requested refiner cannot be constructed."""


class RefinerRuntimeError(RuntimeError):
    """Raised when an available refiner fails while processing a frame."""
