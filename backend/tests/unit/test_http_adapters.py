"""HTTP component checks using the shared pinned FastAPI/HTTPX dependencies.

These isolate health/static adapters. Full application composition is tested
separately against the shared app and real PostgreSQL fixtures.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import build_health_router
from app.services.static_frontend import mount_frontend


class HealthHttpTests(TestCase):
    def client(self, probe):
        app = FastAPI()
        app.include_router(build_health_router(check_database=probe))
        return TestClient(app)

    def test_liveness_never_calls_the_database(self):
        probe = Mock(side_effect=RuntimeError("unavailable"))
        with self.client(probe) as client:
            response = client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        probe.assert_not_called()

    def test_readiness_success_calls_probe_once(self):
        probe = Mock()
        with self.client(probe) as client:
            response = client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        probe.assert_called_once_with()

    def test_readiness_failure_is_503_and_does_not_leak(self):
        probe = Mock(side_effect=RuntimeError("postgresql://private:SYNTHETIC_SECRET@host/db SQL SELECT"))
        with self.client(probe) as client:
            response = client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": {"code": "SERVICE_UNAVAILABLE", "message": "Service temporarily unavailable", "details": []}})
        self.assertNotIn("SYNTHETIC_SECRET", response.text)
        self.assertNotIn("SELECT", response.text)


class StaticHttpTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "index.html").write_text("<!doctype html><title>Test fixture</title>")
        (self.root / "release.json").write_text('{"commit":"synthetic"}')
        app = FastAPI()
        app.include_router(build_health_router(check_database=Mock()))
        mount_frontend(app, self.root)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_unknown_api_and_health_paths_are_not_html(self):
        for path in ("/api", "/api/v1/unknown", "/health/unknown"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("text/html", response.headers.get("content-type", ""))

    def test_real_health_route_wins_over_spa(self):
        response = self.client.get("/health/live")
        self.assertEqual(response.json(), {"status": "ok"})

    def test_spa_route_and_head(self):
        response = self.client.get("/flags/new-checkout")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        head = self.client.head("/flags/new-checkout")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")

    def test_missing_assets_remain_404_and_release_record_is_json(self):
        self.assertEqual(self.client.get("/assets/missing.js").status_code, 404)
        response = self.client.get("/release.json")
        self.assertIn("application/json", response.headers["content-type"])
        self.assertEqual(response.json(), {"commit": "synthetic"})
