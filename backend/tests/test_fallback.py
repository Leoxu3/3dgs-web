import base64
import sys

from pytest import MonkeyPatch

from backend.app.refinement.difix import create_refiner
from backend.app.refinement.fallback import FallbackRefiner


PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwAD"
    "hgGAWjR9awAAAABJRU5ErkJggg=="
)
SVG_DATA_URL = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>").decode("ascii")
)


def test_fallback_refiner_returns_input_image() -> None:
    image_data_url = "data:image/png;base64,abc123"
    refiner = FallbackRefiner()

    result = refiner.refine(image_data_url)

    assert result.image_data_url == image_data_url
    assert result.status == "fallback"
    assert result.fallback_mode is True


def test_refiner_factory_can_force_fallback(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("REFINER_BACKEND", "fallback")
    monkeypatch.setenv("DIFIX3D_TIMEOUT_SECONDS", "not-a-number")

    refiner = create_refiner()

    assert isinstance(refiner, FallbackRefiner)
    assert refiner.is_fallback is True


def test_refiner_factory_falls_back_without_adapter(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("REFINER_BACKEND", "difix3d_plus")
    monkeypatch.delenv("DIFIX3D_COMMAND", raising=False)
    monkeypatch.delenv("DIFIX3D_PYTHON_CALLABLE", raising=False)

    refiner = create_refiner()
    result = refiner.refine(PNG_DATA_URL)

    assert isinstance(refiner, FallbackRefiner)
    assert result.image_data_url == PNG_DATA_URL
    assert result.status == "fallback"
    assert result.fallback_mode is True
    assert "Difix3D unavailable / fallback mode" in result.message


def test_command_refiner_returns_command_output(tmp_path, monkeypatch: MonkeyPatch) -> None:
    script = tmp_path / "copy_refiner.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes())\n",
        encoding="ascii",
    )
    monkeypatch.setenv("REFINER_BACKEND", "difix3d_plus")
    monkeypatch.setenv(
        "DIFIX3D_COMMAND",
        f"{sys.executable} {script} {{input}} {{output}}",
    )
    monkeypatch.delenv("DIFIX3D_PYTHON_CALLABLE", raising=False)

    refiner = create_refiner()
    result = refiner.refine(PNG_DATA_URL, camera={"yaw": 1})

    assert result.image_data_url == PNG_DATA_URL
    assert result.refiner == "difix3d_plus-command-refiner"
    assert result.status == "ok"
    assert result.fallback_mode is False


def test_command_refiner_runtime_error_preserves_fallback(
    tmp_path,
    monkeypatch: MonkeyPatch,
) -> None:
    script = tmp_path / "failing_refiner.py"
    script.write_text("import sys\nsys.exit(7)\n", encoding="ascii")
    monkeypatch.setenv("REFINER_BACKEND", "difix3d")
    monkeypatch.setenv(
        "DIFIX3D_COMMAND",
        f"{sys.executable} {script} {{input}} {{output}}",
    )
    monkeypatch.delenv("DIFIX3D_PYTHON_CALLABLE", raising=False)

    refiner = create_refiner()
    result = refiner.refine(PNG_DATA_URL)

    assert result.image_data_url == PNG_DATA_URL
    assert result.status == "fallback"
    assert result.fallback_mode is True
    assert "failed / fallback mode" in result.message


def test_configured_refiner_skips_svg_placeholder_before_command(
    tmp_path,
    monkeypatch: MonkeyPatch,
) -> None:
    marker = tmp_path / "command-ran.txt"
    script = tmp_path / "marker_refiner.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        f"Path({str(marker)!r}).write_text('ran', encoding='ascii')\n"
        "Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes())\n",
        encoding="ascii",
    )
    monkeypatch.setenv("REFINER_BACKEND", "difix3d")
    monkeypatch.setenv(
        "DIFIX3D_COMMAND",
        f"{sys.executable} {script} {{input}} {{output}}",
    )
    monkeypatch.delenv("DIFIX3D_PYTHON_CALLABLE", raising=False)

    refiner = create_refiner()
    result = refiner.refine(SVG_DATA_URL)

    assert result.image_data_url == SVG_DATA_URL
    assert result.status == "fallback"
    assert result.fallback_mode is True
    assert "SVG placeholder input" in result.message
    assert not marker.exists()
