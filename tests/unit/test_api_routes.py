from fastapi.testclient import TestClient
import pytest

@pytest.fixture(autouse=True)
def clear_overrides(api_main):
    yield
    api_main.app.dependency_overrides.clear()

def test_health_returns_ok(api_main):
  client = TestClient(api_main.app)

  response = client.get("/healt")

  assert response.status_code == 200
  assert response.json() == {"status": "ok"}