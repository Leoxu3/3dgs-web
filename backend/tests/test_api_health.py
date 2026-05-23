from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["headless_server_friendly"] is True
    assert data["desktop_gui_required"] is False


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
    assert data["renderer"] == "stub-svg-renderer"


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
