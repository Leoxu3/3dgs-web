import sys

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.app.main import create_app


def test_render_then_idle_refine_pipeline_passes_camera(
    tmp_path,
    monkeypatch: MonkeyPatch,
) -> None:
    script = tmp_path / "assert_camera_refiner.py"
    script.write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "camera = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))\n"
        "if abs(camera.get('yaw', 0) - 0.42) > 1e-9:\n"
        "    raise SystemExit(9)\n"
        "Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes())\n",
        encoding="ascii",
    )
    monkeypatch.setenv("RENDERER_BACKEND", "mock")
    monkeypatch.setenv("REFINER_BACKEND", "difix3d_plus")
    monkeypatch.setenv(
        "DIFIX3D_COMMAND",
        f"{sys.executable} {script} {{input}} {{output}} {{camera}}",
    )
    monkeypatch.delenv("DIFIX3D_PYTHON_CALLABLE", raising=False)

    client = TestClient(create_app())
    camera = {
        "yaw": 0.42,
        "pitch": 0.1,
        "distance": 2.5,
        "target": [0.1, -0.2, 0.3],
        "fov": 45,
        "up_axis": "z",
    }

    render_response = client.post(
        "/api/render",
        json={
            "camera": camera,
            "width": 320,
            "height": 240,
            "quality": "idle",
        },
    )

    assert render_response.status_code == 200
    raw = render_response.json()
    assert raw["image_data_url"].startswith("data:image/svg+xml;base64,")

    refine_response = client.post(
        "/api/refine",
        json={
            "image_data_url": raw["image_data_url"],
            "camera": camera,
        },
    )

    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert refined["image_data_url"] == raw["image_data_url"]
    assert refined["status"] == "ok"
    assert refined["fallback_mode"] is False
