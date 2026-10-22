from unittest import TestCase
from unittest.mock import Mock

from scripts.operations.db_guard import (
    SafetyError, database_identity, probe_test_database, require_safe_test_database,
)

DEV = "postgresql+psycopg://synthetic:disposable@127.0.0.1:5432/feature_flags_dev"
TEST = "postgresql+psycopg://synthetic:disposable@127.0.0.1:5432/feature_flags_test"


class DatabaseGuardTests(TestCase):
    def settings(self, **changes):
        environment = {"APP_ENV": "test", "DATABASE_URL": DEV, "TEST_DATABASE_URL": TEST}
        environment.update(changes)
        return require_safe_test_database(environment)

    def test_accepts_distinct_loopback_dev_test_targets(self):
        settings = self.settings()
        self.assertEqual(settings.identity.database, "feature_flags_test")
        self.assertNotIn("disposable", repr(settings))

    def test_loopback_aliases_normalize_even_with_different_users_and_drivers(self):
        first = database_identity(TEST)
        second = database_identity("postgresql://other:different@localhost/feature_flags_test")
        third = database_identity("postgresql://other:different@[::1]:5432/feature_flags_test")
        self.assertEqual(first, second)
        self.assertEqual(first, third)

    def test_same_database_under_a_different_url_is_rejected(self):
        for dev in (TEST, "postgresql://other:different@localhost/feature_flags_test", "postgresql://other:different@[::1]/feature_flags_test"):
            with self.subTest(alias=dev):
                with self.assertRaises(SafetyError):
                    self.settings(DATABASE_URL=dev)

    def test_requires_test_mode_and_both_explicit_urls(self):
        for changes in ({"APP_ENV": "development"}, {"APP_ENV": "production"}, {"APP_ENV": ""}, {"DATABASE_URL": ""}, {"TEST_DATABASE_URL": ""}):
            with self.subTest(changes=changes):
                with self.assertRaises(SafetyError):
                    self.settings(**changes)

    def test_remote_or_wrong_database_is_rejected(self):
        for value in (TEST.replace("127.0.0.1", "example.com"), TEST.replace("127.0.0.1", "10.0.0.1"), TEST.replace("feature_flags_test", "feature_flags_dev"), TEST.replace("feature_flags_test", "demo")):
            with self.subTest(url=value):
                with self.assertRaises(SafetyError):
                    self.settings(TEST_DATABASE_URL=value)

    def test_rejects_libpq_redirects_services_and_unsafe_options(self):
        queries = (
            "host=example.com", "hostaddr=1.2.3.4", "dbname=demo", "service=demo", "port=9999",
            "options=-c%20search_path%3Dpublic", "user=postgres", "password=another",
            "connect_timeout=100", "connect_timeout=0", "sslmode=invalid",
            "sslmode=require&sslmode=disable", "connect_timeout=2&connect_timeout=3",
        )
        for query in queries:
            with self.subTest(query=query):
                with self.assertRaises(SafetyError):
                    self.settings(TEST_DATABASE_URL=TEST + "?" + query)

    def test_permits_explicit_bounded_tls_timeout_options(self):
        self.settings(TEST_DATABASE_URL=TEST + "?sslmode=require&channel_binding=require&connect_timeout=2")

    def test_invalid_urls_do_not_echo_credentials(self):
        values = ("sqlite:///feature_flags_test", " " + TEST, TEST + "#secret", TEST + "\n", TEST.replace(":5432", ":99999"), TEST.replace(":5432", ":0"), "postgresql:///feature_flags_test", TEST.replace("127.0.0.1", "127.0.0.1,example.com"))
        for value in values:
            with self.subTest(url=value):
                with self.assertRaises(SafetyError) as result:
                    self.settings(TEST_DATABASE_URL=value)
                self.assertNotIn("disposable", str(result.exception))

    def connection(self, database="feature_flags_test", version=180000):
        cursor = Mock()
        cursor.fetchone.return_value = (database, version)
        cursor_context = Mock()
        cursor_context.__enter__ = Mock(return_value=cursor)
        cursor_context.__exit__ = Mock(return_value=False)
        connection = Mock()
        connection.cursor.return_value = cursor_context
        connection_context = Mock()
        connection_context.__enter__ = Mock(return_value=connection)
        connection_context.__exit__ = Mock(return_value=False)
        return Mock(return_value=connection_context), cursor

    def test_actual_version_probe_is_read_only_and_returns_no_dsn(self):
        connect, cursor = self.connection(version=180003)
        report = probe_test_database(self.settings(), connect)
        self.assertEqual(report["server_major"], 18)
        cursor.execute.assert_called_once_with("SELECT current_database(), current_setting('server_version_num')::integer")
        self.assertEqual(connect.call_args.kwargs["connect_timeout"], 2)
        self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs["options"])
        self.assertNotIn("disposable", str(report))

    def test_wrong_server_major_or_actual_database_blocks_setup(self):
        for database, version in (("feature_flags_test", 170001), ("feature_flags_test", 190000), ("feature_flags_test", "180000"), ("demo", 180000)):
            with self.subTest(database=database, version=version):
                connect, _ = self.connection(database, version)
                with self.assertRaises(SafetyError):
                    probe_test_database(self.settings(), connect)

    def test_connection_failure_is_sanitized(self):
        with self.assertRaises(SafetyError) as result:
            probe_test_database(self.settings(), Mock(side_effect=RuntimeError("postgresql://private:SECRET@private-host")))
        self.assertNotIn("SECRET", str(result.exception))
        self.assertNotIn("private-host", str(result.exception))
