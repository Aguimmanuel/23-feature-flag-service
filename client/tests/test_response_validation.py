"""Successful HTTP status is not permission to coerce malformed decisions."""

import httpx
import pytest

from client.feature_flag_client import FeatureFlagClient

VALID = {
    "flag_key": "new-checkout", "environment": "staging", "value": True,
    "reason": "ROLLOUT_INCLUDED", "bucket": 261,
}


@pytest.mark.parametrize("changes", [
    {"value": "false"}, {"value": "true"}, {"value": 0}, {"value": 1}, {"value": None},
    {"reason": 7}, {"reason": []}, {"reason": "UNKNOWN"},
    {"value": False}, {"reason": "ROLLOUT_EXCLUDED"},
    {"bucket": True}, {"bucket": "261"}, {"bucket": 261.5}, {"bucket": -1},
    {"bucket": 10000}, {"bucket": None},
    {"flag_key": "another-flag"}, {"environment": "production"},
    {"reason": "GROUP_MATCH", "bucket": 261},
    {"reason": "FLAG_DISABLED", "value": True, "bucket": None},
])
def test_malformed_200_response_fails_closed(changes):
    attempts = []
    def handler(request):
        attempts.append(request)
        return httpx.Response(200, json={**VALID, **changes})
    with FeatureFlagClient("http://testserver", "synthetic-key", transport=httpx.MockTransport(handler)) as client:
        result = client.evaluate("new-checkout", "staging", "user-003")
    assert result["value"] is False
    assert result["reason"] == "CLIENT_FALLBACK"
    assert result["fallback"] is True
    assert len(attempts) == 1


@pytest.mark.parametrize("missing", list(VALID))
def test_every_contract_response_field_is_required(missing):
    payload = {key: value for key, value in VALID.items() if key != missing}
    with FeatureFlagClient(
        "http://testserver", "synthetic-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    ) as client:
        assert client.evaluate("new-checkout", "staging", "user-003")["fallback"] is True


@pytest.mark.parametrize("reason,value,bucket", [
    ("FLAG_DISABLED", False, None), ("GROUP_MATCH", True, None),
    ("ROLLOUT_INCLUDED", True, 0), ("ROLLOUT_EXCLUDED", False, 9999),
])
def test_all_valid_decision_shapes_are_preserved(reason, value, bucket):
    payload = {**VALID, "reason": reason, "value": value, "bucket": bucket}
    with FeatureFlagClient(
        "http://testserver", "synthetic-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    ) as client:
        assert client.evaluate("new-checkout", "staging", "user-003") == {
            "value": value, "reason": reason, "fallback": False,
        }
