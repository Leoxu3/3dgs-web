"""Fallback refinement that returns the input image unchanged."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RefinementResult:
    image_data_url: str
    latency_ms: float
    refiner: str
    status: str
    message: str
    fallback_mode: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "image_data_url": self.image_data_url,
            "latency_ms": round(self.latency_ms, 2),
            "refiner": self.refiner,
            "status": self.status,
            "message": self.message,
            "fallback_mode": self.fallback_mode,
        }


class FallbackRefiner:
    name = "fallback-refiner"
    is_fallback = True

    def __init__(self, reason: str = "Difix3D unavailable / fallback mode") -> None:
        self.reason = reason

    def refine(self, image_data_url: str) -> RefinementResult:
        start = time.perf_counter()
        elapsed_ms = (time.perf_counter() - start) * 1000
        return RefinementResult(
            image_data_url=image_data_url,
            latency_ms=elapsed_ms,
            refiner=self.name,
            status="fallback",
            message=self.reason,
            fallback_mode=True,
        )
