"""Tests for app.auth.APITokenMiddleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import APITokenMiddleware
from config import settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "api_token", "secret-deploy-token")
    app = FastAPI()
    app.add_middleware(APITokenMiddleware)

    @app.get("/health")
    def _health() -> dict:
        return {"ok": True}

    @app.get("/api/projects")
    def _projects() -> dict:
        return {"projects": []}

    @app.post("/upload")
    def _upload() -> dict:
        return {"job_id": "abc"}

    @app.get("/bitrix/widget")
    def _widget() -> dict:
        return {"html": "..."}

    return TestClient(app)


def test_health_is_exempt(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_widget_is_unprotected(client: TestClient) -> None:
    # /bitrix/widget is the HTML container; it serves the JS that calls /api/*.
    assert client.get("/bitrix/widget").status_code == 200


def test_api_without_token_returns_401(client: TestClient) -> None:
    resp = client.get("/api/projects")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_api_with_wrong_token_returns_401(client: TestClient) -> None:
    resp = client.get("/api/projects", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_api_with_correct_token_passes(client: TestClient) -> None:
    resp = client.get(
        "/api/projects",
        headers={"Authorization": "Bearer secret-deploy-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"projects": []}


def test_upload_is_protected(client: TestClient) -> None:
    assert client.post("/upload").status_code == 401
    resp = client.post(
        "/upload", headers={"Authorization": "Bearer secret-deploy-token"}
    )
    assert resp.status_code == 200


def test_options_passes_without_token(client: TestClient) -> None:
    # CORS preflight must reach the CORS middleware without auth.
    resp = client.options("/api/projects")
    # No CORS middleware configured here, so 405 is fine — the point is auth
    # did NOT block it with 401.
    assert resp.status_code != 401


def test_missing_server_token_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_token", "")
    app = FastAPI()
    app.add_middleware(APITokenMiddleware)

    @app.get("/api/x")
    def _x() -> dict:
        return {}

    resp = TestClient(app).get("/api/x", headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 500
    assert "BUILDCONTROL_API_TOKEN" in resp.json()["detail"]


def test_constant_time_compare_resists_prefix_match(client: TestClient) -> None:
    # Bearer "secret" (a prefix of the real token) must be rejected.
    resp = client.get("/api/projects", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 401
