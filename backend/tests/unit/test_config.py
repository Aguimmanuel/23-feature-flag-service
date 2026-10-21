import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import create_database_engine, create_session_factory


def build(settings, **changes):
    return Settings(_env_file=None, **{**settings.model_dump(), **changes})


@pytest.mark.parametrize("url", [
    "sqlite:///data.db", "postgresql+asyncpg://u@localhost/db", "not-a-url",
    "postgresql://u@localhost/", "postgresql://u@localhost:bad/db",
])
def test_only_valid_sync_postgresql_connections(settings, url):
    with pytest.raises(ValidationError):
        build(settings, database_url=url)


@pytest.mark.parametrize("secret", ["", " padded", "padded ", "a\nb", "REPLACE_WITH_A_RANDOM_SECRET"])
def test_invalid_secrets(settings, secret):
    with pytest.raises(ValidationError):
        build(settings, admin_token=secret)


def test_credentials_are_required_distinct_and_redacted(settings):
    with pytest.raises(ValidationError):
        build(settings, admin_token=settings.evaluation_api_key)
    assert settings.admin_token.get_secret_value() not in repr(settings)
    marker = "do-not-echo-this-secret\n"
    with pytest.raises(ValidationError) as exc:
        build(settings, admin_token=marker)
    assert marker not in str(exc.value)


def test_missing_configuration_fails_without_reading_local_env(monkeypatch):
    for key in ("DATABASE_URL", "ADMIN_TOKEN", "EVALUATION_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_env_file_loads_but_explicit_environment_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("APP_ENV=development\nTEST_DATABASE_URL=ignored\n")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@127.0.0.1/db")
    monkeypatch.setenv("ADMIN_TOKEN", "distinct-admin")
    monkeypatch.setenv("EVALUATION_API_KEY", "distinct-evaluation")
    assert Settings(_env_file=env).app_env == "test"


@pytest.mark.parametrize("origins", ["*", "https://example.com,*", "file://local"])
def test_cors_rejects_wildcards_and_non_http_origins(settings, origins):
    with pytest.raises(ValueError):
        build(settings, allowed_origins=origins).cors_origins


def test_engine_creation_is_lazy_and_normalizes_driver(settings):
    configured = build(settings, database_url="postgresql://u@127.0.0.1:1/feature_flags_dev")
    engine = create_database_engine(configured)
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.hide_parameters
        factory = create_session_factory(engine)
        with factory() as session:
            assert not session.in_transaction()
    finally:
        engine.dispose()
