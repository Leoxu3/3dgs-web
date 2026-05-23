from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from pytest import MonkeyPatch

from backend.app.main import create_app
from backend.app.rendering import factory
from backend.app.rendering import gsplat_renderer
from backend.app.rendering.gsplat_renderer import GsplatUnavailable
from backend.app.rendering.mock import MockRenderer
from backend.app.rendering.ply_loader import describe_ply


def test_health_endpoint(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("RENDERER_BACKEND", "mock")
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["headless_server_friendly"] is True
    assert data["desktop_gui_required"] is False
    assert data["renderer"] == "mock-svg-renderer"
    assert isinstance(app.state.renderer, MockRenderer)


def test_render_endpoint_returns_data_url(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("RENDERER_BACKEND", "mock")
    client = TestClient(create_app())
    response = client.post(
        "/api/render",
        json={
            "camera": {
                "yaw": 0,
                "pitch": 0,
                "distance": 3,
                "target": [0, 0, 0],
                "fov": 45,
            },
            "width": 320,
            "height": 240,
            "quality": "interactive",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["image_data_url"].startswith("data:image/svg+xml;base64,")
    assert data["renderer"] == "mock-svg-renderer"


def test_renderer_backend_can_force_mock() -> None:
    renderer = factory.create_renderer(renderer_backend="mock")

    assert isinstance(renderer, MockRenderer)


def test_renderer_factory_falls_back_when_gsplat_is_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    def unavailable_renderer(scene_ply_path: str, gsplat_device: str):
        raise GsplatUnavailable("test unavailable")

    monkeypatch.setattr(factory, "_create_gsplat_renderer", unavailable_renderer)

    renderer = factory.create_renderer(renderer_backend="gsplat")

    assert isinstance(renderer, MockRenderer)
    assert renderer.fallback_reason == "gsplat unavailable: test unavailable"


def test_gsplat_backend_validation_rejects_missing_cuda_extension(
    monkeypatch: MonkeyPatch,
) -> None:
    renderer = object.__new__(gsplat_renderer.GsplatRenderer)

    def fake_import_module(module_name: str):
        if module_name == "gsplat.cuda._backend":
            return SimpleNamespace(_C=None)
        raise AssertionError(f"unexpected import: {module_name}")

    monkeypatch.setattr(gsplat_renderer.importlib, "import_module", fake_import_module)

    with pytest.raises(GsplatUnavailable, match="CUDA extension"):
        renderer._validate_gsplat_cuda_backend(torch=SimpleNamespace())


def test_orbit_camera_view_matrix_preserves_left_right_orientation() -> None:
    np = pytest.importorskip("numpy")
    from backend.app.rendering.camera import CameraState

    viewmat = gsplat_renderer.orbit_camera_view_matrix(camera=CameraState(), np=np)
    rotation = viewmat[:3, :3]
    point_right = np.array([1.0, 0.0, 0.0, 1.0], dtype=np.float32)
    point_center = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)

    assert np.linalg.det(rotation) == pytest.approx(1.0, abs=1e-5)
    assert (viewmat @ point_right)[0] > (viewmat @ point_center)[0]


def test_orbit_camera_view_matrix_uses_z_up_by_default() -> None:
    np = pytest.importorskip("numpy")
    from backend.app.rendering.camera import CameraState

    viewmat = gsplat_renderer.orbit_camera_view_matrix(camera=CameraState(), np=np)
    point_up = np.array([0.0, 0.0, 1.0, 1.0], dtype=np.float32)
    point_center = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)

    assert (viewmat @ point_center)[2] > 0.0
    assert (viewmat @ point_up)[1] < (viewmat @ point_center)[1]


def test_orbit_camera_view_matrix_can_use_y_up() -> None:
    np = pytest.importorskip("numpy")
    from backend.app.rendering.camera import CameraState

    viewmat = gsplat_renderer.orbit_camera_view_matrix(camera=CameraState(up_axis="y"), np=np)
    point_up = np.array([0.0, 1.0, 0.0, 1.0], dtype=np.float32)
    point_center = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)

    assert (viewmat @ point_center)[2] > 0.0
    assert (viewmat @ point_up)[1] < (viewmat @ point_center)[1]


def test_ply_description_reads_vertical_axis(tmp_path) -> None:
    scene_file = tmp_path / "z_up.ply"
    scene_file.write_text(
        "ply\n"
        "format ascii 1.0\n"
        "comment Vertical Axis: z\n"
        "element vertex 0\n"
        "end_header\n",
        encoding="ascii",
    )

    description = describe_ply(str(scene_file))

    assert description["vertical_axis"] == "z"


def test_mock_render_changes_with_camera(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("RENDERER_BACKEND", "mock")
    client = TestClient(create_app())
    base_payload = {
        "camera": {
            "yaw": 0,
            "pitch": 0,
            "distance": 3,
            "target": [0, 0, 0],
            "fov": 45,
        },
        "width": 320,
        "height": 240,
        "quality": "interactive",
    }

    first = client.post("/api/render", json=base_payload)
    moved = client.post(
        "/api/render",
        json={
            **base_payload,
            "camera": {
                **base_payload["camera"],
                "yaw": 0.7,
                "pitch": 0.3,
                "distance": 2.2,
                "target": [0.4, -0.1, 0.2],
            },
        },
    )

    assert first.status_code == 200
    assert moved.status_code == 200
    assert first.json()["image_data_url"] != moved.json()["image_data_url"]


def test_scene_path_can_be_set_and_cleared(tmp_path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SCENE_PLY_PATH", raising=False)
    monkeypatch.setenv("RENDERER_BACKEND", "mock")
    scene_file = tmp_path / "demo_scene.ply"
    scene_file.write_text("ply\nformat ascii 1.0\nend_header\n", encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    response = client.post("/api/scene", json={"path": str(scene_file)})

    assert response.status_code == 200
    data = response.json()
    expected_path = str(scene_file.resolve())
    assert data["scene"]["path"] == expected_path
    assert data["scene"]["exists"] is True
    assert data["scene"]["is_ply"] is True
    assert app.state.scene_manager.scene_ply_path == expected_path
    assert app.state.renderer.scene_ply_path == expected_path

    clear_response = client.delete("/api/scene")

    assert clear_response.status_code == 200
    assert clear_response.json()["scene"]["path"] is None
    assert app.state.scene_manager.scene_ply_path == ""
    assert app.state.renderer.scene_ply_path == ""


def test_scene_path_rejects_missing_ply(tmp_path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("SCENE_PLY_PATH", raising=False)
    monkeypatch.setenv("RENDERER_BACKEND", "mock")
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/scene", json={"path": str(tmp_path / "missing.ply")})

    assert response.status_code == 422
    assert response.json()["detail"] == "Scene PLY path does not exist"
    assert app.state.scene_manager.scene_ply_path == ""
    assert app.state.renderer.scene_ply_path == ""
