from fastapi.testclient import TestClient
import pytest

@pytest.fixture(autouse=True)
def clear_overrides(api_main):
    yield
    api_main.app.dependency_overrides.clear()

def make_client(api_main, rows=()):
    def fake_reader(symbol, hours):
        return list(rows)

    api_main.app.dependency_overrides[api_main.get_reader] = lambda: fake_reader

    return TestClient(api_main.app)

def test_health_returns_ok(api_main):
  client = TestClient(api_main.app)

  response = client.get("/healt")

  assert response.status_code == 200
  assert response.json() == {"status": "ok"}

def test_candles_returns_the_serialised_rows(api_main, _candle_row):
    client = make_client(api_main, rows=[_candle_row()])

    response = client.get("/candles?symbol=NVDA")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "NVDA"
    assert body[0]["open"] == 100.0

def test_candles_with_no_rows_returns_an_empty_list(api_main):
    client = make_client(api_main, rows=[])

    response = client.get("/candles?symbol=NVDA")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 0