import pytest
from fastapi.testclient import TestClient

from settlequote.api import create_app
from tests.conftest import friday_payload


def client(tmp_path) -> TestClient:
    app = create_app(str(tmp_path / "calls.db"), free_limit=10, salt="test")
    return TestClient(app)


def test_free_quote_returns_the_friday_fixture(tmp_path):
    response = client(tmp_path).post("/v1/quote/free", json=friday_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["rail"] == "fedwire"
    assert "not financial, legal, or payments advice" in body["disclaimer"]


def test_eleventh_free_call_is_429(tmp_path, monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "settlequote")
    http = client(tmp_path)
    payload = friday_payload()
    for index in range(10):
        response = http.post(
            "/v1/quote/free",
            json=payload,
            headers={"fly-client-ip": "203.0.113.10"},
        )
        assert response.status_code == 200, index
    blocked = http.post(
        "/v1/quote/free",
        json=payload,
        headers={"fly-client-ip": "203.0.113.10"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "free_tier_exhausted"
    assert blocked.json()["paid_url"] == "/v1/quote"
    other = http.post(
        "/v1/quote/free",
        json=payload,
        headers={"fly-client-ip": "203.0.113.11"},
    )
    assert other.status_code == 200


def test_spoofed_forwarded_for_does_not_reset_the_free_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "settlequote")
    app = create_app(str(tmp_path / "calls.db"), free_limit=2, salt="test")
    http = TestClient(app)
    payload = friday_payload()
    for index in range(2):
        response = http.post(
            "/v1/quote/free",
            json=payload,
            headers={
                "fly-client-ip": "203.0.113.10",
                "x-forwarded-for": f"198.51.100.{index}",
            },
        )
        assert response.status_code == 200, index
    blocked = http.post(
        "/v1/quote/free",
        json=payload,
        headers={
            "fly-client-ip": "203.0.113.10",
            "x-forwarded-for": "198.51.100.99",
        },
    )
    assert blocked.status_code == 429


def test_x_forwarded_for_alone_does_not_create_a_new_bucket(tmp_path):
    app = create_app(str(tmp_path / "calls.db"), free_limit=2, salt="test")
    http = TestClient(app)
    payload = friday_payload()
    for index in range(2):
        response = http.post(
            "/v1/quote/free",
            json=payload,
            headers={"x-forwarded-for": f"198.51.100.{index}"},
        )
        assert response.status_code == 200, index
    blocked = http.post(
        "/v1/quote/free",
        json=payload,
        headers={"x-forwarded-for": "203.0.113.8"},
    )
    assert blocked.status_code == 429


def test_fly_client_ip_is_ignored_off_fly(tmp_path, monkeypatch):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    app = create_app(str(tmp_path / "calls.db"), free_limit=2, salt="test")
    http = TestClient(app)
    payload = friday_payload()
    for index in range(2):
        response = http.post(
            "/v1/quote/free",
            json=payload,
            headers={"fly-client-ip": f"203.0.113.{index}"},
        )
        assert response.status_code == 200, index
    blocked = http.post(
        "/v1/quote/free",
        json=payload,
        headers={"fly-client-ip": "203.0.113.99"},
    )
    assert blocked.status_code == 429


def test_bad_amount_is_400(tmp_path):
    payload = friday_payload()
    payload["amount_usd"] = "0"
    response = client(tmp_path).post("/v1/quote/free", json=payload)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_amount"


def test_nan_amount_is_400_not_500(tmp_path):
    http = client(tmp_path)
    for raw in ("NaN", "sNaN", "1e-30"):
        payload = friday_payload()
        payload["amount_usd"] = raw
        response = http.post("/v1/quote/free", json=payload)
        assert response.status_code == 400, raw
        assert response.json()["error"] == "invalid_amount"


def test_json_number_amount_is_400_for_sub_cent_and_200_for_whole_dollars(tmp_path):
    http = client(tmp_path)
    whole = friday_payload()
    whole["amount_usd"] = 12000
    assert http.post("/v1/quote/free", json=whole).status_code == 200
    tiny = friday_payload()
    tiny["amount_usd"] = 0.001
    response = http.post("/v1/quote/free", json=tiny)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_amount"


def test_path_like_timezone_is_400(tmp_path):
    payload = friday_payload()
    payload["receiver_timezone"] = "../x"
    response = client(tmp_path).post("/v1/quote/free", json=payload)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_receiver_timezone"


def test_paid_route_does_not_return_a_quote(tmp_path):
    response = client(tmp_path).post("/v1/quote", json=friday_payload())
    assert response.status_code == 402
    assert response.json()["error"] == "payment_required"
    assert "rails" not in response.json()


def test_dashboard_shows_the_free_call(tmp_path):
    http = client(tmp_path)
    assert http.post("/v1/quote/free", json=friday_payload()).status_code == 200
    page = http.get("/dashboard")
    assert page.status_code == 200
    assert 'id="total-calls">1<' in page.text
    assert 'id="free-calls">1<' in page.text
    assert 'id="error-rate">0%<' in page.text


def test_index_shows_a_sample_and_the_repo(tmp_path):
    page = client(tmp_path).get("/")
    assert page.status_code == 200
    assert "12000.00" in page.text
    assert "fedwire" in page.text
    assert 'href="/dashboard"' in page.text
    assert "https://github.com/alpeshranjan/settlequote" in page.text


def test_a_missing_salt_refuses_to_start(tmp_path, monkeypatch):
    monkeypatch.delenv("IP_HASH_SALT", raising=False)
    with pytest.raises(RuntimeError, match="IP_HASH_SALT"):
        create_app(str(tmp_path / "calls.db"))


def test_health_and_methodology(tmp_path):
    http = client(tmp_path)
    health = http.get("/health")
    assert health.status_code == 200
    assert health.json()["rules_version"] == "2026-10-21"
    method = http.get("/v1/methodology")
    assert method.status_code == 200
    assert "FedNow" in " ".join(method.json()["refuses"])
