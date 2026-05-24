"""Fallback refinement that returns the input image unchanged."""

from __future__ import annotations

import time
from typing import Any

from backend.app.refinement.base import RefinementResult


class FallbackRefiner:
    name = "fallback-refiner"
    is_fallback = True

    def __init__(self, reason: str = "Difix3D unavailable / fallback mode") -> None:
        self.reason = reason

    def refine(
        self,
        image_data_url: str,
        camera: dict[str, Any] | None = None,
    ) -> RefinementResult:
        _ = camera
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
