import asyncio
import json

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, TimeoutError as DatabaseTimeoutError

from app.auth import require_admin, require_evaluation_key
from app.errors import APIError
from app.main import create_app
from app.middleware import BodySizeLimitMiddleware, MAX_BODY_BYTES
from app.schemas import EnvironmentUpdate


@pytest.fixture
def client(settings):
    app = create_app(settings)

    # These probe routes exist only in this test application, never in production.
    @app.get("/probe/admin", dependencies=[Depends(require_admin)])
    def admin():
        return {"ok": True}

    @app.get("/probe/evaluate", dependencies=[Depends(require_evaluation_key)])
    def evaluate():
        return {"ok": True}

    @app.put("/probe/config", dependencies=[Depends(require_admin)])
    def config(data: EnvironmentUpdate):
        return data

    @app.get("/probe/domain-error")
    def domain_error():
        raise APIError(409, "VERSION_CONFLICT", "Configuration version is stale")

    @app.get("/probe/unexpected")
    def unexpected():
        raise RuntimeError("internal-secret-do-not-leak")

    @app.get("/probe/database-error")
    def db_error():
        raise OperationalError("sensitive-sql", {"password": "do-not-leak"}, Exception("sensitive-host"))

    @app.get("/probe/pool-timeout")
    def pool_timeout():
        raise DatabaseTimeoutError("sensitive pool internals")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def admin_headers(settings):
    return {"Authorization": f"Bearer {settings.admin_token.get_secret_value()}"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic invalid"}, {"Authorization": "Bearer wrong"}])
def test_admin_requires_correct_bearer(client, headers):
    response = client.get("/probe/admin", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.json()["error"]["details"] == []


def test_credential_types_are_not_interchangeable(client, settings):
    evaluation = settings.evaluation_api_key.get_secret_value()
    admin = settings.admin_token.get_secret_value()
    assert client.get("/probe/admin", headers={"Authorization": f"Bearer {evaluation}"}).status_code == 401
    assert client.get("/probe/admin", headers={"X-API-Key": evaluation}).status_code == 401
    assert client.get("/probe/evaluate", headers={"X-API-Key": admin}).status_code == 401
    assert client.get("/probe/evaluate", headers=admin_headers(settings)).status_code == 401
    assert client.get("/probe/admin", headers=admin_headers(settings)).status_code == 200
    assert client.get("/probe/evaluate", headers={"X-API-Key": evaluation}).status_code == 200


def test_unicode_wrong_credential_does_not_crash(client):
    response = client.get("/probe/admin", headers=[(b"Authorization", b"Bearer \xff")])
    assert response.status_code == 401


def test_validation_envelope_does_not_echo_input(client, settings):
    response = client.put("/probe/config", headers=admin_headers(settings), json={
        "enabled": True, "target_groups": [], "rollout_percentage": "secret-input", "version": 1,
    })
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "rollout_percentage"
    assert "secret-input" not in response.text


def test_malformed_json_normalizes_errors(client, settings):
    response = client.put("/probe/config", headers={**admin_headers(settings), "Content-Type": "application/json"}, content=b'{broken')
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_oversized_declared_body(client):
    response = client.put("/probe/config", content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.parametrize("path,status,code", [
    ("/probe/domain-error", 409, "VERSION_CONFLICT"),
    ("/probe/unexpected", 500, "INTERNAL_ERROR"),
    ("/probe/database-error", 503, "SERVICE_UNAVAILABLE"),
    ("/probe/pool-timeout", 503, "SERVICE_UNAVAILABLE"),
])
def test_errors_are_sanitized(client, path, status, code):
    response = client.get(path)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "sensitive" not in response.text
    assert "do-not-leak" not in response.text
    assert "internal-secret" not in response.text


def test_unknown_api_route_is_json_not_spa_html(client):
    response = client.get("/api/v1/not-a-route")
    assert response.status_code == 404
    assert "error" in response.json()


def test_explicit_cors_origin_is_honoured(settings):
    configured = settings.model_copy(update={"allowed_origins": "https://dashboard.example"})
    with TestClient(create_app(configured)) as client:
        accepted = client.options("/api/v1/flags", headers={
            "Origin": "https://dashboard.example", "Access-Control-Request-Method": "POST",
        })
        rejected = client.options("/api/v1/flags", headers={
            "Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST",
        })
    assert accepted.headers["access-control-allow-origin"] == "https://dashboard.example"
    assert "access-control-allow-origin" not in rejected.headers


def test_environment_loaded_cors_is_honoured(settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", settings.database_url.get_secret_value())
    monkeypatch.setenv("ADMIN_TOKEN", settings.admin_token.get_secret_value())
    monkeypatch.setenv("EVALUATION_API_KEY", settings.evaluation_api_key.get_secret_value())
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://dashboard.example")
    with TestClient(create_app()) as client:
        response = client.options("/api/v1/flags", headers={
            "Origin": "https://dashboard.example", "Access-Control-Request-Method": "POST",
        })
    assert response.headers["access-control-allow-origin"] == "https://dashboard.example"


@pytest.mark.parametrize("sizes,status", [([MAX_BODY_BYTES], 204), ([16000, 16000], 204), ([16000, 17000], 413)])
def test_body_limit_counts_streamed_chunks_without_content_length(sizes, status):
    called = []
    async def downstream(scope, receive, send):
        called.append(True)
        message = await receive()
        assert len(message["body"]) == sum(sizes)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    messages = [{"type": "http.request", "body": b"x" * size, "more_body": i < len(sizes)-1} for i, size in enumerate(sizes)]
    sent = []
    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "headers": [], "method": "POST", "path": "/"}
    asyncio.run(BodySizeLimitMiddleware(downstream)(scope, receive, send))
    assert sent[0]["status"] == status
    assert bool(called) is (status == 204)
    if status == 413:
        assert json.loads(sent[1]["body"])["error"]["code"] == "PAYLOAD_TOO_LARGE"
