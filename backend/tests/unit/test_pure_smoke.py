from types import SimpleNamespace
from unittest import TestCase

from scripts.operations.smoke import check_responses, validate_url

SHA = "a" * 40


def response(status, payload=None, content_type="application/json"):
    return SimpleNamespace(status_code=status, headers={"content-type": content_type}, json=lambda: payload)


class SmokeTests(TestCase):
    def test_url_rejects_credentials_non_tls_remote_and_query_strings(self):
        for value in ("https://user:secret@example.com", "http://example.com", "https://example.com?token=secret", "https://example.com/unsafe-prefix", "https://example.com#fragment", " https://example.com", "https://example.com\n"):
            with self.subTest(url=value):
                with self.assertRaises(ValueError):
                    validate_url(value)
        self.assertEqual(validate_url("https://example.com/"), "https://example.com")
        self.assertEqual(validate_url("http://127.0.0.1:8000"), "http://127.0.0.1:8000")

    def test_five_read_only_checks_and_no_bodies_in_report(self):
        responses = {
            "/health/live": response(200, {"status": "ok"}),
            "/health/ready": response(200, {"status": "ready"}),
            "/release.json": response(200, {"commit": SHA, "branch": "main"}),
            "/api/v1/smoke-check-not-found": response(404, {"private": "SYNTHETIC_SENTINEL"}),
            "/health/smoke-check-not-found": response(404),
        }
        requested = []
        def get(path):
            requested.append(path)
            return responses[path]
        report = check_responses(get, SHA)
        self.assertEqual(report["requests"], 5)
        self.assertEqual(report["failures"], 0)
        self.assertEqual(len(requested), 5)
        self.assertNotIn("SYNTHETIC_SENTINEL", str(report))

    def test_html_api_404_and_wrong_release_are_failures(self):
        def get(path):
            if path == "/health/live":
                return response(200, {"status": "ok"})
            if path == "/health/ready":
                return response(200, {"status": "ready"})
            if path == "/release.json":
                return response(200, {"commit": "b" * 40, "branch": "main"})
            return response(404, content_type="text/html")
        self.assertEqual(check_responses(get, SHA)["failures"], 3)

    def test_request_exceptions_never_appear_as_success_or_leak(self):
        def get(path):
            raise RuntimeError("SYNTHETIC_SECRET")
        report = check_responses(get, SHA)
        self.assertEqual(report["failures"], 5)
        self.assertNotIn("SYNTHETIC_SECRET", str(report))
