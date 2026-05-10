"""Tests for GET /api/whoami — the SPA bootstrap endpoint."""

from fastapi.testclient import TestClient

from app.webhook_handler import app

client = TestClient(app)


def test_whoami_default_is_standalone() -> None:
    r = client.get("/api/whoami")
    assert r.status_code == 200
    body = r.json()
    assert body["host"] == "standalone"
    assert body["role"] == "director"
    assert "chat" in body["capabilities"]


def test_whoami_detects_bitrix_via_query_param() -> None:
    r = client.get("/api/whoami?bx24_domain=foo.bitrix24.ru")
    assert r.status_code == 200
    assert r.json()["host"] == "bitrix"


def test_whoami_detects_bitrix_via_header() -> None:
    r = client.get("/api/whoami", headers={"x-bx24-domain": "foo.bitrix24.ru"})
    assert r.status_code == 200
    assert r.json()["host"] == "bitrix"


def test_spa_catchall_returns_html_for_client_route() -> None:
    # When the SPA hasn't been built, this returns 503 — that's fine for CI
    # without a Node toolchain. Only assert that it's not a 404.
    r = client.get("/projects/123")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert "text/html" in r.headers["content-type"]


def test_spa_catchall_does_not_swallow_api_404() -> None:
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
