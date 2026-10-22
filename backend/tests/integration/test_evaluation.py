"""Integration tests for the evaluation routes.

Covers test-plan.md B-series cases:
  B01: Both evaluation routes with valid credentials -> same payload
  B02: Unknown/archived flag -> 404 FLAG_NOT_FOUND (not successful false)
  B03: Missing configuration -> 404 ENVIRONMENT_CONFIG_NOT_FOUND
  B04: Missing/blank user ID, invalid groups, wrong field types -> 422
  B05: Save then evaluate after commit -> uses committed settings

These require PostgreSQL 18 per technical-spec.md section 9. They follow
the shared integration test pattern (create_app + SessionDependency override).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Flag, FlagEnvironment
from app.domain.evaluator import compute_bucket

pytestmark = pytest.mark.integration


def evaluation_headers(client):
    return {"X-API-Key": client.app.state.settings.evaluation_api_key.get_secret_value()}


def admin_headers(client):
    token = client.app.state.settings.admin_token.get_secret_value()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app_client(settings, session_factory) -> TestClient:
    """TestClient wired to the test database via dependency override."""
    app = create_app(settings)

    def session_override():
        with session_factory() as session:
            yield session

    app.dependency_overrides[__import__("app.db", fromlist=["get_session"]).get_session] = session_override

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _seed_flag(session: Session, key: str, archived: bool = False) -> Flag:
    """Seed a flag with all three environment rows."""
    existing = session.query(Flag).filter(Flag.key == key).one_or_none()
    if existing is not None:
        return existing
    flag = Flag(key=key, description="test flag", archived=archived)
    session.add(flag)
    session.flush()
    for env in ("development", "staging", "production"):
        session.add(
            FlagEnvironment(
                flag_id=flag.id,
                environment=env,
                enabled=False,
                target_groups=[],
                rollout_percentage=0,
            )
        )
    session.flush()
    return flag


def _post_evaluate(client: TestClient, body: dict[str, Any], headers: dict[str, str] | None = None):
    return client.post("/api/v1/evaluate", json=body, headers=headers or {})


# ---------------------------------------------------------------------------
# B01: Both evaluation routes return the same payload
# ---------------------------------------------------------------------------


def test_both_evaluation_routes_same_payload(app_client, session_factory):
    """B01: /evaluate and /admin/evaluate return identical decisions."""
    with session_factory() as session:
        flag = _seed_flag(session, "new-checkout")
        staging = next(
            e for e in flag.environments if e.environment == "staging"
        )
        staging.enabled = True
        staging.target_groups = ["beta"]
        staging.rollout_percentage = 25
        session.commit()

    body = {
        "flag_key": "new-checkout",
        "environment": "staging",
        "user": {"id": "user-003", "groups": []},
    }

    client_resp = app_client.post(
        "/api/v1/evaluate",
        json=body,
        headers=evaluation_headers(app_client),
    )
    admin_resp = app_client.post(
        "/api/v1/admin/evaluate",
        json=body,
        headers=admin_headers(app_client),
    )

    assert client_resp.status_code == 200
    assert admin_resp.status_code == 200
    assert client_resp.json() == admin_resp.json()
    assert client_resp.json() == {
        "flag_key": "new-checkout",
        "environment": "staging",
        "value": True,
        "reason": "ROLLOUT_INCLUDED",
        "bucket": 261,
    }


# ---------------------------------------------------------------------------
# B02: Unknown/archived flag -> 404 FLAG_NOT_FOUND
# ---------------------------------------------------------------------------


def test_unknown_flag_404(app_client, session_factory):
    """B02: Unknown flag -> 404 FLAG_NOT_FOUND, not successful false."""
    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "does-not-exist",
            "environment": "staging",
            "user": {"id": "user-001", "groups": []},
        },
        headers=evaluation_headers(app_client),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FLAG_NOT_FOUND"


def test_archived_flag_404(app_client, session_factory):
    """B02: Archived flag -> 404 FLAG_NOT_FOUND."""
    with session_factory() as session:
        _seed_flag(session, "archived-flag", archived=True)
        session.commit()

    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "archived-flag",
            "environment": "staging",
            "user": {"id": "user-001", "groups": []},
        },
        headers=evaluation_headers(app_client),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FLAG_NOT_FOUND"


# ---------------------------------------------------------------------------
# B03: Missing configuration -> 404 ENVIRONMENT_CONFIG_NOT_FOUND
# ---------------------------------------------------------------------------


def test_missing_config_404(app_client, session_factory):
    """B03: Flag exists but environment config missing -> 404."""
    with session_factory() as session:
        flag = _seed_flag(session, "partial-flag")
        session.query(FlagEnvironment).filter(
            FlagEnvironment.environment == "production",
            FlagEnvironment.flag_id == flag.id,
        ).delete()
        session.commit()

    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "partial-flag",
            "environment": "production",
            "user": {"id": "user-001", "groups": []},
        },
        headers=evaluation_headers(app_client),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ENVIRONMENT_CONFIG_NOT_FOUND"


# ---------------------------------------------------------------------------
# B04: Validation errors -> 422 before decision
# ---------------------------------------------------------------------------


def test_missing_user_id_422(app_client, session_factory):
    """B04: Missing/blank user_id -> 422, no false success."""
    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "new-checkout",
            "environment": "staging",
            "user": {"id": "", "groups": []},
        },
        headers=evaluation_headers(app_client),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_groups_422(app_client, session_factory):
    """B04: Invalid groups (duplicates) -> 422."""
    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "new-checkout",
            "environment": "staging",
            "user": {"id": "user-001", "groups": ["beta", "beta"]},
        },
        headers=evaluation_headers(app_client),
    )
    assert resp.status_code == 422


def test_invalid_flag_key_422(app_client, session_factory):
    """B04: Invalid flag key format -> 422."""
    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "Invalid Key!",
            "environment": "staging",
            "user": {"id": "user-001", "groups": []},
        },
        headers=evaluation_headers(app_client),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Auth tests: missing/wrong credential -> 401
# ---------------------------------------------------------------------------


def test_missing_eval_key_401(app_client, session_factory):
    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "new-checkout",
            "environment": "staging",
            "user": {"id": "user-001", "groups": []},
        },
    )
    assert resp.status_code == 401


def test_wrong_eval_key_401(app_client, session_factory):
    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "new-checkout",
            "environment": "staging",
            "user": {"id": "user-001", "groups": []},
        },
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_missing_admin_token_401(app_client, session_factory):
    resp = app_client.post(
        "/api/v1/admin/evaluate",
        json={
            "flag_key": "new-checkout",
            "environment": "staging",
            "user": {"id": "user-001", "groups": []},
        },
    )
    assert resp.status_code == 401


def test_wrong_admin_token_401(app_client, session_factory):
    resp = app_client.post(
        "/api/v1/admin/evaluate",
        json={
            "flag_key": "new-checkout",
            "environment": "staging",
            "user": {"id": "user-001", "groups": []},
        },
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# B05: Save then evaluate after commit -> committed settings used
# ---------------------------------------------------------------------------


def test_evaluate_uses_committed_settings(app_client, session_factory):
    """B05: After a config save + commit, evaluation reads committed values."""
    with session_factory() as session:
        flag = _seed_flag(session, "persist-flag")
        staging = next(
            e for e in flag.environments if e.environment == "staging"
        )
        staging.enabled = True
        staging.target_groups = ["beta"]
        staging.rollout_percentage = 50
        session.commit()

    expected_bucket = compute_bucket("persist-flag", "user-001")

    resp = app_client.post(
        "/api/v1/evaluate",
        json={
            "flag_key": "persist-flag",
            "environment": "staging",
            "user": {"id": "user-001", "groups": []},
        },
        headers=evaluation_headers(app_client),
    )
    assert resp.status_code == 200
    assert resp.json()["value"] is False
    assert resp.json()["reason"] == "ROLLOUT_EXCLUDED"
    assert resp.json()["bucket"] == expected_bucket
