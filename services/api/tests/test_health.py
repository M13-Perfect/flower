from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok_status() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "flower-api",
        "version": "0.1.0",
    }


def test_health_allows_desktop_dev_origin() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_health_allows_alternate_loopback_dev_origin() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"Origin": "http://127.0.0.1:5199"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5199"
