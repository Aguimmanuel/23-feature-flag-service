"""Fail closed before migrations or destructive test cleanup."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Connection, URL, make_url
from sqlalchemy.exc import ArgumentError

from app.config import BACKEND_DIR


class TestDatabaseSettings(BaseSettings):
    __test__ = False
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", extra="ignore", hide_input_in_errors=True,
    )
    app_env: str
    database_url: SecretStr
    test_database_url: SecretStr


class UnsafeTestDatabase(RuntimeError):
    pass


def _parse(value: str) -> URL:
    try:
        url = make_url(value)
        _ = url.port
    except (ArgumentError, ValueError):
        raise UnsafeTestDatabase("Invalid database configuration") from None
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise UnsafeTestDatabase("Only PostgreSQL test databases are permitted")
    if not url.host or not url.database or not url.username:
        raise UnsafeTestDatabase("Explicit host, user and database are required")
    # libpq query parameters can override host/database/service identity.
    if url.query:
        raise UnsafeTestDatabase("Test URLs must not contain connection query overrides")
    return url


def _identity(url: URL) -> tuple[str, int, str]:
    host = "loopback" if url.host in {"localhost", "127.0.0.1", "::1"} else url.host
    return host, url.port or 5432, url.database


def verified_test_url(settings: TestDatabaseSettings) -> URL:
    if settings.app_env != "test":
        raise UnsafeTestDatabase("Set APP_ENV=test before persistence tests")
    test_url = _parse(settings.test_database_url.get_secret_value())
    dev_url = _parse(settings.database_url.get_secret_value())
    if test_url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise UnsafeTestDatabase("Test host must be loopback; remote deletion is forbidden")
    if test_url.database != "feature_flags_test":
        raise UnsafeTestDatabase("Test database name must be feature_flags_test")
    if _identity(test_url) == _identity(dev_url):
        raise UnsafeTestDatabase("Development and test database identities must differ")
    return test_url.set(drivername="postgresql+psycopg")


def verify_test_server(connection: Connection) -> None:
    row = connection.execute(text(
        "SELECT current_database(), current_setting('server_version_num')::int, "
        "host(inet_server_addr())"
    )).one()
    if row[0] != "feature_flags_test" or row[1] // 10000 != 18 or row[2] not in {"127.0.0.1", "::1"}:
        raise UnsafeTestDatabase("Server identity/version does not match isolated PostgreSQL 18")
