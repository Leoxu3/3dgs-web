"""Difix3D integration point.

The skeleton keeps this module intentionally light. A later phase can replace
the fallback object with a real Difix3D / Difix3D+ adapter while preserving the
same `refine(image_data_url)` method.
"""

from __future__ import annotations

from backend.app.refinement.fallback import FallbackRefiner


def create_refiner() -> FallbackRefiner:
    try:
        import difix3d  # type: ignore[import-not-found]  # noqa: F401
    except Exception as exc:
        return FallbackRefiner(
            reason=f"Difix3D unavailable / fallback mode ({exc.__class__.__name__})"
        )

    return FallbackRefiner(
        reason="Difix3D import detected, but real adapter is not implemented yet"
    )
