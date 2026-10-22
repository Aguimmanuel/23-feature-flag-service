"""Runtime and generated contract checks independent from database availability."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import InterfaceError

from app.main import create_app
from app.schemas import FlagCreate


def test_generated_error_schemas_match_the_runtime_envelope(settings):
    schema = create_app(settings).openapi()
    for path, method in (
        ("/api/v1/flags", "post"),
        ("/api/v1/flags/{key}/environments/{environment}", "put"),
        ("/api/v1/evaluate", "post"),
        ("/api/v1/admin/evaluate", "post"),
    ):
        response = schema["paths"][path][method]["responses"]["422"]
        reference = response["content"]["application/json"]["schema"]["$ref"]
        model = schema["components"]["schemas"][reference.rsplit("/", 1)[1]]
        assert "error" in model["properties"], (path, model)


@pytest.mark.parametrize("content_type", [None, "text/plain"])
def test_api_body_requires_explicit_json_content_type(settings, content_type):
    app = create_app(settings)
    @app.post("/api/v1/contract-probe")
    def probe(data: FlagCreate):
        return data
    headers = {} if content_type is None else {"Content-Type": content_type}
    with TestClient(app) as client:
        response = client.post("/api/v1/contract-probe", content=json.dumps({"key": "example"}), headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_json_charset_is_accepted(settings):
    app = create_app(settings)
    @app.post("/api/v1/contract-probe")
    def probe(data: FlagCreate):
        return data
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/contract-probe", content=json.dumps({"key": "example"}),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    assert response.status_code == 200


def test_disconnected_database_interface_is_503_not_500(settings):
    app = create_app(settings)
    @app.get("/contract-probe/database-disconnected")
    def probe():
        raise InterfaceError("sensitive-sql", {}, Exception("private database details"))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/contract-probe/database-disconnected")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "private" not in response.text and "sensitive" not in response.text
