from fastapi.testclient import TestClient

from template_repository.app import app


class TestHealth:
    def test_health_returns_ok(self) -> None:
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
