import pytest

from tests.database_safety import TestDatabaseSettings, UnsafeTestDatabase, verified_test_url, verify_test_server

DEV = "postgresql+psycopg://user@127.0.0.1:5432/feature_flags_dev"
TEST = "postgresql+psycopg://user@127.0.0.1:5432/feature_flags_test"


def config(**changes):
    return TestDatabaseSettings(_env_file=None, **{
        "app_env": "test", "database_url": DEV, "test_database_url": TEST, **changes,
    })


@pytest.mark.parametrize("changes", [
    {"app_env": "development"},
    {"test_database_url": "sqlite:///test.db"},
    {"test_database_url": "postgresql://user@remote.example/feature_flags_test"},
    {"test_database_url": "postgresql://user@127.0.0.1/feature_flags_dev"},
    {"test_database_url": "postgresql://user@127.0.0.1/feature_flags_test?host=remote.example"},
    {"test_database_url": "postgresql://user@127.0.0.1/feature_flags_test?service=live"},
    {"test_database_url": "postgresql://user@127.0.0.1/feature_flags_test?dbname=live"},
    {"test_database_url": "postgresql://user@127.0.0.1/feature_flags_test?options=-csearch_path=live"},
    {"test_database_url": "not-a-url"},
    {"test_database_url": "postgresql://user@localhost:bad/feature_flags_test"},
    {"test_database_url": "postgresql://localhost/feature_flags_test"},
    {"database_url": TEST},
    {"database_url": "postgresql://another-user@localhost:5432/feature_flags_test"},
    {"database_url": "postgresql://another-user@[::1]/feature_flags_test"},
])
def test_unsafe_configuration_fails_before_database_access(changes):
    with pytest.raises(UnsafeTestDatabase):
        verified_test_url(config(**changes))


def test_safe_url_normalizes_driver():
    url = verified_test_url(config(test_database_url=TEST.replace("+psycopg", "")))
    assert url.drivername == "postgresql+psycopg"
    assert url.database == "feature_flags_test"


@pytest.mark.parametrize("row", [
    ("feature_flags_dev", 180006, "127.0.0.1"),
    ("feature_flags_test", 170001, "127.0.0.1"),
    ("feature_flags_test", 180006, "192.0.2.1"),
])
def test_server_response_must_match_database_version_and_address(row):
    class Result:
        def one(self):
            return row
    class Connection:
        def execute(self, statement):
            return Result()
    with pytest.raises(UnsafeTestDatabase):
        verify_test_server(Connection())
