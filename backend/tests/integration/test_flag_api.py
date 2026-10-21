from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db import get_session
from app.main import create_app
from app.models import AuditLog, Flag, FlagEnvironment
from app.services.flags import get_audit_writer
from tests.audit_helpers import database_test_writer


@pytest.fixture
def client(settings, session_factory):
    app = create_app(settings)
    def session_override():
        with session_factory() as session:
            yield session
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_audit_writer] = lambda: database_test_writer
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers['Authorization'] = 'Bearer ' + settings.admin_token.get_secret_value()
        yield client


def create(client, key="new-checkout"):
    response = client.post('/api/v1/flags', json={'key': key, 'description': 'Test description'})
    assert response.status_code == 201, response.text
    return response.json()


def config(**changes):
    return {'enabled': True, 'target_groups': [], 'rollout_percentage': 25, 'version': 1, **changes}


def test_create_defaults_and_audit(client, session_factory):
    response = client.post('/api/v1/flags', json={'key': 'new-checkout'})
    assert response.status_code == 201
    assert response.headers['Location'] == '/api/v1/flags/new-checkout'
    body = response.json()
    assert body['description'] == '' and not body['archived']
    assert [row['environment'] for row in body['environments']] == ['development', 'staging', 'production']
    assert all(not row['enabled'] and row['rollout_percentage'] == 0 and row['version'] == 1 and row['target_groups'] == [] for row in body['environments'])
    with session_factory() as session:
        audit = session.scalar(select(AuditLog))
        assert audit.action == 'FLAG_CREATED' and audit.actor == 'shared-admin'
        assert audit.before_state is None and audit.after_state['key'] == 'new-checkout'


def test_list_pagination_order_and_description_update(client):
    create(client, 'zebra')
    create(client, 'alpha')
    page = client.get('/api/v1/flags?limit=1&offset=0').json()
    assert page['total'] == 2 and len(page['items']) == 1 and page['items'][0]['key'] == 'alpha'
    response = client.patch('/api/v1/flags/alpha', json={'description': 'Changed'})
    assert response.status_code == 200 and response.json()['description'] == 'Changed'
    assert client.get('/api/v1/flags/alpha').json()['description'] == 'Changed'


def test_archive_hides_and_reserves_key(client):
    create(client)
    assert client.post('/api/v1/flags', json={'key': 'new-checkout'}).status_code == 409
    archived = client.delete('/api/v1/flags/new-checkout')
    assert archived.status_code == 204 and archived.content == b''
    assert client.get('/api/v1/flags').json()['total'] == 0
    assert client.get('/api/v1/flags/new-checkout').status_code == 404
    assert client.patch('/api/v1/flags/new-checkout', json={'description': 'changed'}).status_code == 404
    assert client.put('/api/v1/flags/new-checkout/environments/staging', json=config()).status_code == 404
    assert client.delete('/api/v1/flags/new-checkout').status_code == 404
    duplicate = client.post('/api/v1/flags', json={'key': 'new-checkout'})
    assert duplicate.status_code == 409 and duplicate.json()['error']['code'] == 'FLAG_KEY_CONFLICT'


def test_configuration_isolated_sorted_and_versioned(client, session_factory):
    original = create(client)
    response = client.put('/api/v1/flags/new-checkout/environments/staging', json=config(target_groups=['pro', 'beta']))
    assert response.status_code == 200
    assert response.json()['target_groups'] == ['beta', 'pro'] and response.json()['version'] == 2
    stale = client.put('/api/v1/flags/new-checkout/environments/staging', json=config())
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'VERSION_CONFLICT'
    after = client.get('/api/v1/flags/new-checkout').json()
    assert after['environments'][0] == original['environments'][0]
    assert after['environments'][2] == original['environments'][2]
    with session_factory() as session:
        changes = session.scalars(select(AuditLog).where(AuditLog.action == 'CONFIG_UPDATED')).all()
        assert len(changes) == 1
        assert changes[0].before_state == {'enabled': False, 'target_groups': [], 'rollout_percentage': 0, 'version': 1}
        assert changes[0].after_state == {'enabled': True, 'target_groups': ['beta', 'pro'], 'rollout_percentage': 25, 'version': 2}


def test_identical_successful_save_still_increments_version(client):
    create(client)
    values = config(enabled=False, rollout_percentage=0)
    assert client.put('/api/v1/flags/new-checkout/environments/staging', json=values).json()['version'] == 2


@pytest.mark.parametrize('percentage', [-1, 101, 1.5, True, '25'])
def test_invalid_percentage_creates_no_audit(client, session_factory, percentage):
    create(client)
    response = client.put('/api/v1/flags/new-checkout/environments/staging', json=config(rollout_percentage=percentage))
    assert response.status_code == 422
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.parametrize('path', [
    '/api/v1/flags?limit=0', '/api/v1/flags?limit=101', '/api/v1/flags?offset=-1',
    '/api/v1/flags/BadKey',
])
def test_invalid_path_and_query(client, path):
    assert client.get(path).status_code == 422


def test_invalid_environment_unknown_fields_and_malformed_json(client):
    create(client)
    assert client.put('/api/v1/flags/new-checkout/environments/invalid', json=config()).status_code == 422
    assert client.patch('/api/v1/flags/new-checkout', json={'description': 'x', 'key': 'new-key'}).status_code == 422
    assert client.post('/api/v1/flags', content=b'{broken', headers={'Content-Type': 'application/json'}).status_code == 422


def test_missing_configuration_is_an_error_not_created_implicitly(client, session_factory):
    create(client)
    with session_factory.begin() as session:
        session.execute(delete(FlagEnvironment).where(FlagEnvironment.environment == 'staging'))
    response = client.put('/api/v1/flags/new-checkout/environments/staging', json=config())
    assert response.status_code == 404 and response.json()['error']['code'] == 'ENVIRONMENT_CONFIG_NOT_FOUND'


def test_real_management_routes_reject_wrong_credentials(client, settings):
    client.headers.pop('Authorization')
    assert client.get('/api/v1/flags').status_code == 401
    response = client.post('/api/v1/flags', json={'key': 'denied'}, headers={'Authorization': 'Bearer ' + settings.evaluation_api_key.get_secret_value()})
    assert response.status_code == 401


def test_missing_production_writer_refuses_mutation_without_partial_data(client, session_factory, monkeypatch):
    from app.audit_contract import AuditWriterUnavailable
    def unavailable():
        raise AuditWriterUnavailable('not integrated')
    monkeypatch.setattr('app.services.flags.load_audit_writer', unavailable)
    client.app.dependency_overrides.pop(get_audit_writer)
    response = client.post('/api/v1/flags', json={'key': 'blocked'})
    assert response.status_code == 503 and response.json()['error']['code'] == 'SERVICE_UNAVAILABLE'
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Flag)) == 0


def test_mutation_rolls_back_when_writer_fails(client, session_factory):
    create(client)
    def failing(**kwargs):
        database_test_writer(**kwargs)
        raise RuntimeError('simulated failure')
    client.app.dependency_overrides[get_audit_writer] = lambda: failing
    response = client.put('/api/v1/flags/new-checkout/environments/staging', json=config())
    assert response.status_code == 500
    after = client.get('/api/v1/flags/new-checkout').json()['environments'][1]
    assert after['version'] == 1 and after['enabled'] is False
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 1


def test_concurrent_same_version_saves_have_one_winner(client, session_factory):
    create(client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.put('/api/v1/flags/new-checkout/environments/staging', json=config()), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'CONFIG_UPDATED')) == 1


def test_concurrent_duplicate_creations_have_one_winner(client):
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post('/api/v1/flags', json={'key': 'race'}), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]


def test_archive_lock_blocks_config_save_then_returns_not_found(client):
    create(client)
    archive_locked = Event()
    release_archive = Event()
    def pausing_writer(**kwargs):
        database_test_writer(**kwargs)
        if kwargs['action'] == 'FLAG_ARCHIVED':
            archive_locked.set()
            if not release_archive.wait(timeout=5):
                raise RuntimeError('test synchronization timeout')
    client.app.dependency_overrides[get_audit_writer] = lambda: pausing_writer
    with ThreadPoolExecutor(max_workers=2) as executor:
        archived = executor.submit(client.delete, '/api/v1/flags/new-checkout')
        try:
            assert archive_locked.wait(timeout=3)
            saved = executor.submit(client.put, '/api/v1/flags/new-checkout/environments/staging', json=config())
            with pytest.raises(TimeoutError):
                saved.result(timeout=0.1)
        finally:
            release_archive.set()
        assert archived.result(timeout=3).status_code == 204
        assert saved.result(timeout=3).status_code == 404
