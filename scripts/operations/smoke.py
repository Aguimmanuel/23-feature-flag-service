"""Five bounded, read-only HTTP checks; never an integration/performance claim.

No network is used without --permission-confirmed. Run only against the team's
approved service. No tokens are sent and response bodies/errors are not logged.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from time import perf_counter
from urllib.parse import urlsplit
from typing import Callable


def validate_url(raw: str) -> str:
    if type(raw) is not str or raw != raw.strip() or any(ord(c) < 33 or ord(c) == 127 for c in raw):
        raise ValueError("Use a clean root URL")
    parsed = urlsplit(raw)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"} or not parsed.hostname:
        raise ValueError("Use a root URL without credentials, query or fragment")
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError("Remote smoke checks require HTTPS")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid URL port")
    return raw.rstrip("/")


def check_responses(get: Callable, expected_commit: str) -> dict:
    checks = []
    paths = ("/health/live", "/health/ready", "/release.json", "/api/v1/smoke-check-not-found", "/health/smoke-check-not-found")
    for path in paths:
        start = perf_counter()
        try:
            response = get(path)
            status = response.status_code
            if path == "/health/live":
                passed = status == 200 and response.json() == {"status": "ok"}
            elif path == "/health/ready":
                passed = status == 200 and response.json() == {"status": "ready"}
            elif path == "/release.json":
                passed = status == 200 and response.json() == {"commit": expected_commit, "branch": "main"}
            else:
                passed = status == 404 and "text/html" not in response.headers.get("content-type", "").lower()
            category = "response"
        except Exception:
            status, passed, category = None, False, "request_or_payload_error"
        checks.append({"path": path, "http_status": status, "status": "PASS" if passed else "FAIL", "category": category, "elapsed_ms": round((perf_counter() - start) * 1000, 3)})
    return {
        "expected_main_commit": expected_commit, "requests": len(checks),
        "failures": sum(check["status"] != "PASS" for check in checks),
        "purpose": "Read-only release smoke; not Q2, persistence proof, or a performance benchmark",
        "warm_cold_conditions": "Operator must record; not inferred by script",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--permission-confirmed", action="store_true")
    arguments = parser.parse_args()
    try:
        base = validate_url(arguments.url)
        if not arguments.permission_confirmed or re.fullmatch(r"[0-9a-f]{40}", arguments.commit) is None:
            raise ValueError("Explicit permission and a full approved main SHA are required")
        import httpx  # The shared pinned requirements, never a separately resolved set.
    except (ValueError, ImportError):
        print("BLOCKED: verify URL, permission, full main SHA and the installed shared pinned requirements")
        return 2
    with httpx.Client(base_url=base, timeout=2.0, follow_redirects=False) as client:
        report = check_responses(client.get, arguments.commit)
    report["url"] = base
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
