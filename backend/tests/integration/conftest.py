"""Real PostgreSQL fixtures. No SQLite or silent skip on unsafe configuration."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from tests.database_safety import TestDatabaseSettings, verified_test_url, verify_test_server

BACKEND = Path(__file__).resolve().parents[2]
TEST_SUITE_LOCK = 62394101


def migration_config(connection) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="session")
def database_engine():
    if os.getenv("PYTEST_XDIST_WORKER"):
        pytest.fail("Parallel destructive database tests require separate schemas")
    url = verified_test_url(TestDatabaseSettings())
    engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 3}, pool_pre_ping=True)
    lock_connection = None
    acquired = False
    try:
        lock_connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        verify_test_server(lock_connection)
        acquired = lock_connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": TEST_SUITE_LOCK})
        if not acquired:
            pytest.fail("Another persistence test suite is using this disposable database")
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
        yield engine
    finally:
        try:
            if lock_connection is not None:
                try:
                    if acquired:
                        lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": TEST_SUITE_LOCK})
                finally:
                    lock_connection.close()
        finally:
            engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(database_engine):
    def clear():
        with database_engine.begin() as connection:
            verify_test_server(connection)
            tables = set(inspect(connection).get_table_names())
            if {"flags", "flag_environments", "audit_logs"} <= tables:
                connection.execute(text("TRUNCATE audit_logs, flag_environments, flags"))
    clear()
    yield
    clear()


@pytest.fixture
def session_factory(database_engine):
    return sessionmaker(bind=database_engine, expire_on_commit=False)
