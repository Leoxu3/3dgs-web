from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.app.main import create_app
from backend.app.rendering.mock import MockRenderer


def test_health_endpoint() -> None:
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


def test_render_endpoint_returns_data_url() -> None:
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


def test_mock_render_changes_with_camera() -> None:
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
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/scene", json={"path": str(tmp_path / "missing.ply")})

    assert response.status_code == 422
    assert response.json()["detail"] == "Scene PLY path does not exist"
    assert app.state.scene_manager.scene_ply_path == ""
    assert app.state.renderer.scene_ply_path == ""
