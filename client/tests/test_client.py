"""Tests for the Python client helper.

Covers test-plan.md H-series cases:
  H01: Success response -> value/reason retained, fallback=False
  H02: Timeout, network, 401/404/503, malformed ->
       false CLIENT_FALLBACK, fallback=True, no retry loop

No server required — uses httpx.MockTransport for deterministic behavior.
"""

from __future__ import annotations

import json

import httpx
import pytest

from client.feature_flag_client import FeatureFlagClient


# ---------------------------------------------------------------------------
# H01: Success response
# ---------------------------------------------------------------------------

def test_client_success_returns_server_values():
    """H01: On success, value/reason retained, fallback=False."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "flag_key": "new-checkout",
                "environment": "staging",
                "value": True,
                "reason": "ROLLOUT_INCLUDED",
                "bucket": 261,
            },
        )

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "test-key", transport=transport
    ) as client:
        result = client.evaluate("new-checkout", "staging", "user-003", [])

    assert result["value"] is True
    assert result["reason"] == "ROLLOUT_INCLUDED"
    assert result["fallback"] is False


def test_client_success_group_match():
    """H01: Group match success returns true/GROUP_MATCH."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "flag_key": "new-checkout",
                "environment": "staging",
                "value": True,
                "reason": "GROUP_MATCH",
                "bucket": None,
            },
        )

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "test-key", transport=transport
    ) as client:
        result = client.evaluate("new-checkout", "staging", "user-001", ["beta"])

    assert result["value"] is True
    assert result["reason"] == "GROUP_MATCH"
    assert "bucket" not in result  # the helper returns only the decision and fallback status
    assert result["fallback"] is False


# ---------------------------------------------------------------------------
# H02: All fallback paths
# ---------------------------------------------------------------------------

def test_client_timeout_fallback():
    """H02: Transport timeout -> false CLIENT_FALLBACK, fallback=True."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Request timed out")

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "test-key", transport=transport
    ) as client:
        result = client.evaluate("new-checkout", "staging", "user-001", [])

    assert result["value"] is False
    assert result["reason"] == "CLIENT_FALLBACK"
    assert result["fallback"] is True


def test_client_network_error_fallback():
    """H02: Network error -> false CLIENT_FALLBACK, fallback=True."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.NetworkError("Connection refused")

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "test-key", transport=transport
    ) as client:
        result = client.evaluate("new-checkout", "staging", "user-001", [])

    assert result["value"] is False
    assert result["reason"] == "CLIENT_FALLBACK"
    assert result["fallback"] is True


def test_client_non_2xx_fallback():
    """H02: Non-2xx response -> false CLIENT_FALLBACK, fallback=True."""
    for status in (401, 404, 500, 503):
        def handler(request: httpx.Request, status=status) -> httpx.Response:
            return httpx.Response(status, json={"detail": "error"})

        transport = httpx.MockTransport(handler)
        with FeatureFlagClient(
            "http://testserver", "test-key", transport=transport
        ) as client:
            result = client.evaluate("new-checkout", "staging", "user-001", [])

        assert result["value"] is False
        assert result["reason"] == "CLIENT_FALLBACK"
        assert result["fallback"] is True, f"status {status}"


def test_client_malformed_payload_fallback():
    """H02: Malformed result -> false CLIENT_FALLBACK, fallback=True."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="not json at all")

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "test-key", transport=transport
    ) as client:
        result = client.evaluate("new-checkout", "staging", "user-001", [])

    assert result["value"] is False
    assert result["reason"] == "CLIENT_FALLBACK"
    assert result["fallback"] is True


def test_client_missing_fields_fallback():
    """H02: Missing required fields -> false CLIENT_FALLBACK, fallback=True."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": True})  # missing reason

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "test-key", transport=transport
    ) as client:
        result = client.evaluate("new-checkout", "staging", "user-001", [])

    assert result["value"] is False
    assert result["reason"] == "CLIENT_FALLBACK"
    assert result["fallback"] is True


def test_client_no_retry_loop():
    """H02: No automatic retries — single attempt on failure."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "test-key", transport=transport
    ) as client:
        result = client.evaluate("new-checkout", "staging", "user-001", [])

    assert result["fallback"] is True
    assert call_count == 1, f"Expected 1 attempt, got {call_count}"


# ---------------------------------------------------------------------------
# Request verification: correct path and header
# ---------------------------------------------------------------------------

def test_client_sends_correct_headers_and_path():
    """Client sends X-API-Key to /api/v1/evaluate."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "flag_key": "new-checkout",
                "environment": "staging",
                "value": False,
                "reason": "ROLLOUT_EXCLUDED",
                "bucket": 5415,
            },
        )

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "secret-key-123", transport=transport
    ) as client:
        client.evaluate("new-checkout", "staging", "user-001", [])

    assert captured["path"] == "/api/v1/evaluate"
    assert captured["headers"].get("x-api-key") == "secret-key-123"


def test_client_sends_correct_body():
    """Client sends flag_key, environment, user.id, user.groups."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "flag_key": "new-checkout",
                "environment": "staging",
                "value": True,
                "reason": "GROUP_MATCH",
                "bucket": None,
            },
        )

    transport = httpx.MockTransport(handler)
    with FeatureFlagClient(
        "http://testserver", "test-key", transport=transport
    ) as client:
        client.evaluate("new-checkout", "staging", "user-003", ["beta", "admin"])

    assert captured["body"] == {
        "flag_key": "new-checkout",
        "environment": "staging",
        "user": {"id": "user-003", "groups": ["beta", "admin"]},
    }
