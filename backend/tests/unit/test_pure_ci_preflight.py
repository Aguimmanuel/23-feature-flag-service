import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.operations.ci_preflight import missing_components


class PreflightTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, path, content):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)

    def test_missing_backend_is_a_blocker_not_a_green_skip(self):
        issues = missing_components(self.root, "backend")
        self.assertIn("Missing shared component: backend/requirements.txt", issues)
        self.assertIn("Missing initial Alembic revision", issues)
        self.assertIn("Missing client helper tests", issues)

    def test_an_independent_lock_is_not_accepted(self):
        self.write("uv.lock", "synthetic")
        self.assertTrue(any("uv.lock" in message for message in missing_components(self.root, "backend")))

    def test_upstream_metadata_only_stub_does_not_become_another_lock(self):
        self.write("backend/uv.lock", 'version = 1\nrevision = 5\nrequires-python = ">=3.12"\n')
        self.assertFalse(any("uv.lock" in message for message in missing_components(self.root, "backend")))

    def test_real_second_resolution_is_rejected(self):
        self.write("backend/uv.lock", 'version = 1\nrequires-python = ">=3.12"\n[[package]]\nname = "another-resolution"\n')
        self.assertTrue(any("uv.lock" in message for message in missing_components(self.root, "backend")))

    def test_unhashed_requirements_are_rejected(self):
        self.write("backend/requirements.txt", "fastapi>=0.1\n")
        self.assertTrue(any("exact pins and hashes" in message for message in missing_components(self.root, "backend")))

    def test_frontend_requires_real_scripts_and_a_lock(self):
        self.write("frontend/package.json", json.dumps({"scripts": {"build": "vite build"}}))
        issues = missing_components(self.root, "frontend")
        self.assertIn("Missing frontend npm script: typecheck", issues)
        self.assertIn("Missing frontend npm script: test", issues)
        self.assertIn("Missing shared component: frontend/package-lock.json", issues)

    def test_invalid_frontend_json_is_a_sanitized_blocker(self):
        self.write("frontend/package.json", "not-json")
        self.assertIn("Invalid frontend package.json", missing_components(self.root, "frontend"))

    def test_complete_frontend_preflight_does_not_claim_test_passes(self):
        self.write("frontend/package.json", json.dumps({"scripts": {"build": "vite build", "test": "vitest", "typecheck": "tsc --noEmit"}}))
        self.write("frontend/package-lock.json", json.dumps({"lockfileVersion": 3}))
        self.write("frontend/src/App.tsx", "// synthetic file presence test; not a real UI")
        self.assertEqual(missing_components(self.root, "frontend"), [])
