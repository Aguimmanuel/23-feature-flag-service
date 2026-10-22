"""Audit and combined API acceptance using the real app and PostgreSQL 18.

The shared integration fixtures verify target identity/version, migrate with a
caller-supplied connection, serialize suites and clean disposable data. These
checks do not override authentication, the session dependency or audit writer.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.audit_contract import load_audit_writer
from app.main import create_app
from app.models import AuditLog, Flag, FlagEnvironment
from app.seed import seed_database
from tests.database_safety import TestDatabaseSettings


@pytest.fixture
def application_settings(settings, session_factory):
    # session_factory forces the shared guarded DB/migration fixture to run
    # BEFORE constructing an app pointed at the exact isolated test target.
    return settings.model_copy(update={
        "database_url": TestDatabaseSettings().test_database_url,
    })


@pytest.fixture
def service_client(application_settings):
    with TestClient(create_app(application_settings), raise_server_exceptions=False) as client:
        client.headers["Authorization"] = "Bearer " + application_settings.admin_token.get_secret_value()
        yield client


def create(client, key="audit-checkout"):
    response = client.post("/api/v1/flags", json={"key": key, "description": "Synthetic baseline"})
    assert response.status_code == 201, response.text
    return response.json()


def config(**changes):
    return {"enabled": True, "target_groups": [], "rollout_percentage": 25, "version": 1, **changes}


def audits(client, key="audit-checkout", **params):
    response = client.get(f"/api/v1/flags/{key}/audit", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_real_create_configure_evaluate_audit_archive_flow(service_client, application_settings):
    client = service_client
    flag = create(client, "new-checkout")
    assert len(flag["environments"]) == 3
    changed = client.put("/api/v1/flags/new-checkout/environments/staging", json=config(target_groups=["pro", "beta"]))
    assert changed.status_code == 200 and changed.json()["version"] == 2
    assert changed.json()["target_groups"] == ["beta", "pro"]
    assert audits(client, "new-checkout")["total"] == 2
    for user, expected, bucket in (("user-001", False, 5415), ("user-003", True, 261)):
        body = {"flag_key": "new-checkout", "environment": "staging", "user": {"id": user, "groups": []}}
        repeated = [client.post("/api/v1/admin/evaluate", json=body) for _ in range(2)]
        assert all(response.status_code == 200 for response in repeated)
        assert repeated[0].json() == repeated[1].json()
        assert repeated[0].json()["value"] is expected
        assert repeated[0].json()["bucket"] == bucket
        external = client.post("/api/v1/evaluate", json=body, headers={"X-API-Key": application_settings.evaluation_api_key.get_secret_value()})
        assert external.status_code == 200 and external.json() == repeated[0].json()
    group = client.post("/api/v1/admin/evaluate", json={"flag_key": "new-checkout", "environment": "staging", "user": {"id": "user-001", "groups": ["beta"]}})
    assert group.json()["reason"] == "GROUP_MATCH" and group.json()["bucket"] is None
    production = client.post("/api/v1/admin/evaluate", json={"flag_key": "new-checkout", "environment": "production", "user": {"id": "user-003", "groups": ["beta"]}})
    assert production.json()["reason"] == "FLAG_DISABLED" and production.json()["value"] is False
    assert audits(client, "new-checkout")["total"] == 2  # no per-evaluation audit
    assert client.delete("/api/v1/flags/new-checkout").status_code == 204
    history = audits(client, "new-checkout")
    assert history["total"] == 3
    assert {row["action"] for row in history["items"]} == {"FLAG_CREATED", "CONFIG_UPDATED", "FLAG_ARCHIVED"}
    assert client.get("/api/v1/flags/new-checkout").status_code == 404
    assert client.post("/api/v1/admin/evaluate", json={"flag_key": "new-checkout", "environment": "staging", "user": {"id": "user-003"}}).status_code == 404
    assert client.post("/api/v1/flags", json={"key": "new-checkout"}).status_code == 409
    assert audits(client, "new-checkout")["total"] == 3


def test_all_actions_and_exact_snapshots(service_client):
    create(service_client)
    assert service_client.patch("/api/v1/flags/audit-checkout", json={"description": "Changed"}).status_code == 200
    assert service_client.put("/api/v1/flags/audit-checkout/environments/staging", json=config(target_groups=["beta"])).status_code == 200
    assert service_client.delete("/api/v1/flags/audit-checkout").status_code == 204
    page = audits(service_client)
    assert page["total"] == 4
    by_action = {entry["action"]: entry for entry in page["items"]}
    assert by_action["FLAG_CREATED"]["before"] is None
    assert by_action["FLAG_UPDATED"]["before"] == {"key": "audit-checkout", "description": "Synthetic baseline", "archived": False}
    assert by_action["FLAG_ARCHIVED"]["after"] == {"key": "audit-checkout", "description": "Changed", "archived": True}
    assert by_action["CONFIG_UPDATED"]["before"] == {"enabled": False, "target_groups": [], "rollout_percentage": 0, "version": 1}
    assert by_action["CONFIG_UPDATED"]["after"] == {"enabled": True, "target_groups": ["beta"], "rollout_percentage": 25, "version": 2}
    for entry in page["items"]:
        assert set(entry) == {"id", "flag_key", "environment", "action", "actor", "before", "after", "created_at"}
        assert entry["actor"] == "shared-admin" and entry["created_at"].endswith("Z")
        assert entry["environment"] == ("staging" if entry["action"] == "CONFIG_UPDATED" else None)


def test_order_ties_pagination_and_archived_access(service_client, session_factory):
    flag = create(service_client)
    # Control timestamps/UUIDs using real rows for a deterministic tie-order test.
    with session_factory.begin() as session:
        session.query(AuditLog).delete()
        for number in (1, 2, 3):
            session.add(AuditLog(
                id=UUID(int=number), flag_id=UUID(flag["id"]), environment=None,
                action="FLAG_UPDATED", actor="shared-admin",
                before_state={"key": "audit-checkout", "description": "Before", "archived": False},
                after_state={"key": "audit-checkout", "description": "After", "archived": False},
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))
        session.get(Flag, UUID(flag["id"])).archived = True
    page = audits(service_client, limit=1, offset=1)
    assert (page["total"], page["limit"], page["offset"]) == (3, 1, 1)
    assert page["items"][0]["id"] == str(UUID(int=2))
    assert audits(service_client, offset=99)["items"] == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "bad"}])
def test_invalid_pagination_has_shared_error_envelope(service_client, params):
    response = service_client.get("/api/v1/flags/unknown/audit", params=params)
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_real_auth_precedes_resource_lookup(service_client, application_settings):
    service_client.headers.pop("Authorization")
    evaluation = application_settings.evaluation_api_key.get_secret_value()
    for headers in ({}, {"X-API-Key": evaluation}, {"Authorization": "Bearer " + evaluation}):
        denied = service_client.get("/api/v1/flags/missing/audit", headers=headers)
        assert denied.status_code == 401 and denied.json()["error"]["code"] == "UNAUTHORIZED"
    service_client.headers["Authorization"] = "Bearer " + application_settings.admin_token.get_secret_value()
    missing = service_client.get("/api/v1/flags/missing/audit")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "FLAG_NOT_FOUND"


def test_history_has_no_mutation_routes(service_client):
    create(service_client)
    for method in ("post", "put", "patch", "delete"):
        assert getattr(service_client, method)("/api/v1/flags/audit-checkout/audit").status_code == 405
    assert audits(service_client)["total"] == 1


def test_invalid_and_stale_changes_do_not_add_events(service_client):
    create(service_client)
    invalid = service_client.put("/api/v1/flags/audit-checkout/environments/staging", json=config(rollout_percentage=101))
    assert invalid.status_code == 422 and audits(service_client)["total"] == 1
    assert service_client.put("/api/v1/flags/audit-checkout/environments/staging", json=config()).status_code == 200
    stale = service_client.put("/api/v1/flags/audit-checkout/environments/staging", json=config())
    assert stale.status_code == 409 and audits(service_client)["total"] == 2


@pytest.mark.parametrize("mutation", ["create", "description", "configuration", "archive"])
def test_real_audit_constraint_failure_rolls_back_each_business_mutation(service_client, session_factory, mutation):
    if mutation != "create":
        create(service_client)
    before_count = 0 if mutation == "create" else 1

    def reject_insert(mapper, connection, target):
        target.action = "INVALID_ACTION"  # actual PostgreSQL CHECK failure

    event.listen(AuditLog, "before_insert", reject_insert)
    try:
        if mutation == "create":
            result = service_client.post("/api/v1/flags", json={"key": "audit-checkout"})
        elif mutation == "description":
            result = service_client.patch("/api/v1/flags/audit-checkout", json={"description": "Must roll back"})
        elif mutation == "configuration":
            result = service_client.put("/api/v1/flags/audit-checkout/environments/staging", json=config())
        else:
            result = service_client.delete("/api/v1/flags/audit-checkout")
    finally:
        event.remove(AuditLog, "before_insert", reject_insert)
    assert result.status_code == 500 and result.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "INVALID_ACTION" not in result.text and "INSERT" not in result.text
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == before_count
        if mutation == "create":
            assert session.scalar(select(func.count()).select_from(Flag)) == 0
            assert session.scalar(select(func.count()).select_from(FlagEnvironment)) == 0
        else:
            flag = session.scalar(select(Flag))
            assert flag.description == "Synthetic baseline" and flag.archived is False
            staging = session.get(FlagEnvironment, (flag.id, "staging"))
            assert staging.version == 1 and staging.enabled is False


def test_two_real_same_version_saves_have_one_winner(service_client):
    create(service_client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: service_client.put("/api/v1/flags/audit-checkout/environments/staging", json=config()), range(2)))
    assert sorted(item.status_code for item in responses) == [200, 409]
    assert sum(item["action"] == "CONFIG_UPDATED" for item in audits(service_client)["items"]) == 1


def test_archive_lock_with_real_writer_blocks_save_then_rejects_it(service_client):
    create(service_client)
    locked, release = Event(), Event()

    def pause_archive(mapper, connection, target):
        if target.action == "FLAG_ARCHIVED":
            locked.set()
            if not release.wait(timeout=5):
                raise RuntimeError("Test synchronization timed out")

    event.listen(AuditLog, "after_insert", pause_archive)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            archived = executor.submit(service_client.delete, "/api/v1/flags/audit-checkout")
            try:
                assert locked.wait(timeout=3)
                saved = executor.submit(service_client.put, "/api/v1/flags/audit-checkout/environments/staging", json=config())
                with pytest.raises(TimeoutError):
                    saved.result(timeout=0.1)
            finally:
                release.set()
            assert archived.result(timeout=4).status_code == 204
            assert saved.result(timeout=4).status_code == 404
    finally:
        event.remove(AuditLog, "after_insert", pause_archive)
    assert audits(service_client)["total"] == 2


def test_real_seed_rerun_and_app_restart_preserve_edits(application_settings, session_factory):
    writer = load_audit_writer()
    seeded = seed_database(session_factory, writer)
    assert seeded.created == ("new-checkout", "search-preview")
    with TestClient(create_app(application_settings)) as client:
        client.headers["Authorization"] = "Bearer " + application_settings.admin_token.get_secret_value()
        saved = client.put("/api/v1/flags/new-checkout/environments/staging", json=config(rollout_percentage=73))
        assert saved.status_code == 200 and saved.json()["version"] == 2
    rerun = seed_database(session_factory, writer)
    assert rerun.created == () and rerun.skipped == ("new-checkout", "search-preview")
    with TestClient(create_app(application_settings)) as fresh_client:
        fresh_client.headers["Authorization"] = "Bearer " + application_settings.admin_token.get_secret_value()
        detail = fresh_client.get("/api/v1/flags/new-checkout").json()
        assert detail["environments"][1]["rollout_percentage"] == 73
        assert detail["environments"][1]["version"] == 2
        assert audits(fresh_client, "new-checkout")["total"] == 2
        assert {item["actor"] for item in audits(fresh_client, "search-preview")["items"]} == {"seed"}


def test_production_health_routes_and_unknown_paths(service_client):
    assert service_client.get("/health/live").json() == {"status": "ok"}
    ready = service_client.get("/health/ready")
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}
    for path in ("/api/v1/missing-route", "/health/missing-route"):
        response = service_client.get(path)
        assert response.status_code == 404 and "error" in response.json()
        assert "text/html" not in response.headers.get("content-type", "")


def test_corrupt_stored_snapshot_does_not_leak(service_client, session_factory):
    create(service_client)
    with session_factory.begin() as session:
        row = session.scalar(select(AuditLog))
        row.after_state = {**row.after_state, "Authorization": "SYNTHETIC_SENTINEL"}
    response = service_client.get("/api/v1/flags/audit-checkout/audit")
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "SYNTHETIC_SENTINEL" not in response.text


def test_actual_app_static_adapter_preserves_reserved_paths(application_settings, tmp_path):
    # Synthetic files are test fixtures only; no fake frontend ships in the app.
    (tmp_path / "index.html").write_text("<!doctype html><title>Fixture</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/app.js").write_text("// test fixture")
    with TestClient(create_app(application_settings, frontend_directory=tmp_path)) as client:
        assert client.get("/flags/example").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/health/live").json() == {"status": "ok"}
        for path in ("/api/unknown", "/health/unknown"):
            response = client.get(path)
            assert response.status_code == 404 and "text/html" not in response.headers.get("content-type", "")
