from backend.app.refinement.fallback import FallbackRefiner


def test_fallback_refiner_returns_input_image() -> None:
    image_data_url = "data:image/png;base64,abc123"
    refiner = FallbackRefiner()

    result = refiner.refine(image_data_url)

    assert result.image_data_url == image_data_url
    assert result.status == "fallback"
    assert result.fallback_mode is True
