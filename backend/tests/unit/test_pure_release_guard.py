import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.operations.release_guard import (
    ReleaseBlocked, checkout_identity, validate_neon_target,
    verify_identity, verify_release_record,
)

SHA = "a" * 40
NEON = "postgresql+psycopg://synthetic:disposable@ep-example.eu-central-1.aws.neon.tech/feature_flags_demo?sslmode=require&channel_binding=require"


class ReleaseGuardTests(TestCase):
    def test_only_exact_full_approved_main_identity_is_accepted(self):
        self.assertEqual(verify_identity(SHA, SHA, "main"), SHA)
        for approved, actual, branch in (("", SHA, "main"), ("a" * 7, SHA, "main"), (SHA, "b" * 40, "main"), (SHA, SHA, "develop"), (SHA, SHA, "feat/audit-integration")):
            with self.subTest(branch=branch, approved=approved, actual=actual):
                with self.assertRaises(ReleaseBlocked):
                    verify_identity(approved, actual, branch)

    def git_results(self, root, *arguments):
        return {
            ("rev-parse", "HEAD"): SHA,
            ("branch", "--show-current"): "main",
            ("merge-base", "--is-ancestor", SHA, "refs/remotes/origin/main"): "",
            ("status", "--porcelain", "--untracked-files=no"): "",
            ("ls-files", "--others", "--exclude-standard", "--", "backend/app", "backend/migrations", "frontend/src", "scripts", ".github", "render.yaml"): "",
        }[arguments]

    def test_checkout_verifies_main_history_and_clean_tracked_tree(self):
        with patch("scripts.operations.release_guard._git", side_effect=self.git_results) as git:
            self.assertEqual(checkout_identity(Path("/synthetic"), {"APPROVED_RELEASE_COMMIT": SHA}), SHA)
        self.assertEqual(git.call_count, 5)

    def test_untracked_application_source_is_blocked(self):
        def untracked(root, *arguments):
            if arguments[0] == "ls-files":
                return "backend/app/unreviewed.py"
            return self.git_results(root, *arguments)
        with patch("scripts.operations.release_guard._git", side_effect=untracked):
            with self.assertRaises(ReleaseBlocked):
                checkout_identity(Path("/synthetic"), {"APPROVED_RELEASE_COMMIT": SHA})

    def test_provider_and_checkout_must_agree(self):
        with patch("scripts.operations.release_guard._git", side_effect=self.git_results):
            with self.assertRaises(ReleaseBlocked):
                checkout_identity(Path("/synthetic"), {"APPROVED_RELEASE_COMMIT": SHA, "RENDER_GIT_COMMIT": "b" * 40})

    def test_dirty_tracked_tree_is_blocked(self):
        def dirty(root, *arguments):
            if arguments[0] == "status":
                return " M backend/app/main.py"
            return self.git_results(root, *arguments)
        with patch("scripts.operations.release_guard._git", side_effect=dirty):
            with self.assertRaises(ReleaseBlocked):
                checkout_identity(Path("/synthetic"), {"APPROVED_RELEASE_COMMIT": SHA})

    def test_exact_build_record_must_match(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            with self.assertRaises(ReleaseBlocked):
                verify_release_record(path, SHA)
            for record in ({"commit": "b" * 40, "branch": "main"}, {"commit": SHA, "branch": "develop"}, {"commit": SHA, "branch": "main", "token": "synthetic"}):
                path.write_text(json.dumps(record))
                with self.assertRaises(ReleaseBlocked):
                    verify_release_record(path, SHA)
            path.write_text(json.dumps({"commit": SHA, "branch": "main"}))
            verify_release_record(path, SHA)

    def test_production_target_needs_explicit_tls_and_matching_identity(self):
        host, database = validate_neon_target({"APP_ENV": "production", "DATABASE_URL": NEON}, expected_host="ep-example.eu-central-1.aws.neon.tech", expected_database="feature_flags_demo", direct_required=True)
        self.assertEqual(database, "feature_flags_demo")
        self.assertTrue(host.endswith(".neon.tech"))

    def test_unsafe_production_targets_are_blocked_without_echoing_secrets(self):
        values = (
            NEON.replace("sslmode=require", "sslmode=disable"),
            NEON.replace("sslmode=require&", ""),
            NEON.replace("postgresql+psycopg", "sqlite"),
            NEON.replace("ep-example.eu-central-1.aws.neon.tech", "example.com"),
            NEON + "&host=another-host", NEON + "&service=another-service",
            NEON + "&sslmode=require", NEON + "&connect_timeout=999",
            NEON.replace("channel_binding=require", "channel_binding=disable"),
        )
        for value in values:
            with self.subTest(url=value):
                with self.assertRaises(ReleaseBlocked) as result:
                    validate_neon_target({"APP_ENV": "production", "DATABASE_URL": value})
                self.assertNotIn("disposable", str(result.exception))

    def test_migrations_require_a_direct_connection(self):
        pooled = NEON.replace("ep-example.", "ep-example-pooler.")
        validate_neon_target({"APP_ENV": "production", "DATABASE_URL": pooled})
        with self.assertRaises(ReleaseBlocked):
            validate_neon_target({"APP_ENV": "production", "DATABASE_URL": pooled}, direct_required=True)

    def test_expected_host_database_and_production_mode_are_enforced(self):
        for environment, host, database in (("test", None, None), ("production", "wrong.neon.tech", None), ("production", None, "wrong_database")):
            with self.subTest(environment=environment, host=host, database=database):
                with self.assertRaises(ReleaseBlocked):
                    validate_neon_target({"APP_ENV": environment, "DATABASE_URL": NEON}, expected_host=host, expected_database=database)
