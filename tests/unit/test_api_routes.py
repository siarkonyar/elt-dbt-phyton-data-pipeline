from fastapi.testclient import TestClient

def test_health_returns_ok(api_main):
  client = TestClient(api_main.app)

  response = client.get("/healt")

  assert response.status_code == 200
  assert response.json() == {"status": "ok"}