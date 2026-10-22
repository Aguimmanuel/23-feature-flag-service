"""Unit isolation must not disable frontend serving or API protections."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_unit_application_does_not_auto_mount_a_generated_frontend(settings):
    app = create_app(settings)
    assert not any(getattr(route, "path", None) == "/{path:path}" for route in app.routes)

    @app.get("/probe/unit-isolation")
    def probe():
        return {"probe": True}

    with TestClient(app) as client:
        assert client.get("/probe/unit-isolation").json() == {"probe": True}


@pytest.mark.parametrize("discovery", ["automatic", "explicit"])
def test_frontend_mount_preserves_real_api_auth_and_error_responses(settings, monkeypatch, tmp_path, discovery):
    # Minimal HTML is a routing fixture, not a replacement production frontend.
    build = tmp_path / "frontend" / "dist"
    build.mkdir(parents=True)
    html = "<!doctype html><title>Routing fixture</title>"
    (build / "index.html").write_text(html)
    if discovery == "automatic":
        monkeypatch.setattr("app.main.PROJECT_ROOT", tmp_path)
        app = create_app(settings)
    else:
        app = create_app(settings, frontend_directory=build)
    with TestClient(app) as client:
        assert client.get("/").text == html
        assert client.get("/flags/example").text == html
        for headers in ({}, {"Authorization": "Bearer invalid-synthetic-token"}):
            response = client.get("/api/v1/flags", headers=headers)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"
        response = client.post("/api/v1/evaluate", json={
            "flag_key": "example", "environment": "staging",
            "user": {"id": "synthetic-user", "groups": []},
        })
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
        assert client.get("/health/live").json() == {"status": "ok"}
        for path in ("/api/v1/missing", "/health/missing", "/assets/missing.js"):
            response = client.get(path)
            assert response.status_code == 404
            assert "error" in response.json()
            assert "text/html" not in response.headers.get("content-type", "")
