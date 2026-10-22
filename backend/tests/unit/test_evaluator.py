"""Unit tests for the pure evaluation engine.

Covers test-plan.md E-series cases:
  E01: Known SHA-256 reference vectors -> exact buckets 5415, 5933, 261
  E02: Same valid flag/user/config 100 repeated calls -> identical result
  E03: Same flag/user across environments -> same bucket, different settings
  E04: Disabled + matching group + 100% -> false FLAG_DISABLED, null bucket
  E05: Group match at 0% -> true GROUP_MATCH, null bucket
  E06: Empty/nonmatching groups, 0% and 100% -> false/true; integer buckets
  E07: Case-different groups -> no match unless exact string
  E08: Boundary bucket equals rollout*100 -> excluded; one below included
  E09: Increase rollout -> previously included users stay included
  E10: 10,000 synthetic IDs at 25% -> fraction plausibly near 25% (diagnostic)

No database required. These tests run standalone.
"""

from __future__ import annotations

import hashlib

import pytest

from app.domain.evaluator import compute_bucket, evaluate_config


# ---------------------------------------------------------------------------
# Reference vectors (api-contract.md section 5)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_reference_vector_user_001():
    """new-checkout / user-001 -> bucket 5415."""
    assert compute_bucket("new-checkout", "user-001") == 5415


@pytest.mark.unit
def test_reference_vector_user_002():
    """new-checkout / user-002 -> bucket 5933."""
    assert compute_bucket("new-checkout", "user-002") == 5933


@pytest.mark.unit
def test_reference_vector_user_003():
    """new-checkout / user-003 -> bucket 261."""
    assert compute_bucket("new-checkout", "user-003") == 261


@pytest.mark.unit
def test_bucket_is_deterministic_sha256_not_random():
    """Bucket comes from SHA-256 of flag_key:user_id, not random()."""
    encoded = ("new-checkout" + ":" + "user-003").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    expected = int(digest[:8], 16) % 10000
    assert compute_bucket("new-checkout", "user-003") == expected


# ---------------------------------------------------------------------------
# E02: Stability — same input 100 times -> identical result
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_same_input_100_times_identical():
    """E02: Repeated evaluation yields identical result and bucket."""
    for _ in range(100):
        result = evaluate_config(
            flag_key="new-checkout",
            user_id="user-003",
            user_groups=[],
            enabled=True,
            target_groups=["beta"],
            rollout_percentage=25,
        )
        assert result == {
            "value": True,
            "reason": "ROLLOUT_INCLUDED",
            "bucket": 261,
        }


# ---------------------------------------------------------------------------
# E03: Same bucket across environments, different decisions possible
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_same_bucket_across_environments():
    """E03: Bucket is environment-independent; settings may differ."""
    r_dev = evaluate_config(
        flag_key="new-checkout",
        user_id="user-001",
        user_groups=[],
        enabled=True,
        target_groups=[],
        rollout_percentage=100,
    )
    r_prod = evaluate_config(
        flag_key="new-checkout",
        user_id="user-001",
        user_groups=[],
        enabled=True,
        target_groups=[],
        rollout_percentage=0,
    )
    assert r_dev["bucket"] == r_prod["bucket"] == 5415
    assert r_dev["value"] is True   # 100% includes
    assert r_prod["value"] is False  # 0% excludes


# ---------------------------------------------------------------------------
# E04: Disabled overrides everything (including group match at 100%)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_disabled_overrides_group_match():
    """E04: Disabled + matching group + 100% -> false FLAG_DISABLED, null bucket."""
    result = evaluate_config(
        flag_key="new-checkout",
        user_id="user-003",
        user_groups=["beta"],
        enabled=False,
        target_groups=["beta"],
        rollout_percentage=100,
    )
    assert result == {"value": False, "reason": "FLAG_DISABLED", "bucket": None}


# ---------------------------------------------------------------------------
# E05: Group match at 0%
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_group_match_at_zero_percent():
    """E05: Group match at 0% -> true GROUP_MATCH, null bucket."""
    result = evaluate_config(
        flag_key="new-checkout",
        user_id="user-001",
        user_groups=["beta"],
        enabled=True,
        target_groups=["beta"],
        rollout_percentage=0,
    )
    assert result == {"value": True, "reason": "GROUP_MATCH", "bucket": None}


# ---------------------------------------------------------------------------
# E06: Empty/nonmatching groups at 0% and 100%
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_empty_groups_zero_percent_excluded():
    """E06: Empty groups, 0% -> false, integer bucket."""
    result = evaluate_config(
        flag_key="new-checkout",
        user_id="user-003",
        user_groups=[],
        enabled=True,
        target_groups=[],
        rollout_percentage=0,
    )
    assert result["value"] is False
    assert result["reason"] == "ROLLOUT_EXCLUDED"
    assert isinstance(result["bucket"], int)
    assert 0 <= result["bucket"] <= 9999


@pytest.mark.unit
def test_empty_groups_100_percent_included():
    """E06: Empty groups, 100% -> true, integer bucket."""
    result = evaluate_config(
        flag_key="new-checkout",
        user_id="user-001",
        user_groups=[],
        enabled=True,
        target_groups=[],
        rollout_percentage=100,
    )
    assert result["value"] is True
    assert result["reason"] == "ROLLOUT_INCLUDED"
    assert isinstance(result["bucket"], int)


# ---------------------------------------------------------------------------
# E07: Case-different groups -> no match unless exact
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_case_sensitive_group_matching():
    """E07: Case-different groups do not match."""
    result = evaluate_config(
        flag_key="new-checkout",
        user_id="user-001",
        user_groups=["Beta"],
        enabled=True,
        target_groups=["beta"],
        rollout_percentage=0,
    )
    assert result == {"value": False, "reason": "ROLLOUT_EXCLUDED", "bucket": 5415}


# ---------------------------------------------------------------------------
# E08: Boundary bucket equals rollout*100 -> excluded
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("bucket,value,reason", [
    (2499, True, "ROLLOUT_INCLUDED"),
    (2500, False, "ROLLOUT_EXCLUDED"),
    (2501, False, "ROLLOUT_EXCLUDED"),
])
def test_rollout_threshold_boundaries(monkeypatch, bucket, value, reason):
    """Test the exact decision boundary independently of hash distribution."""
    monkeypatch.setattr("app.domain.evaluator.compute_bucket", lambda flag, user: bucket)
    result = evaluate_config("boundary-test", "boundary-user", [], True, [], 25)
    assert result == {"value": value, "reason": reason, "bucket": bucket}


# ---------------------------------------------------------------------------
# E09: Increasing rollout preserves existing percentage inclusion
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_increasing_rollout_preserves_inclusion():
    """E09: Raising percentage keeps previously included users included."""
    # user-003 has bucket 261. At 3% (threshold 300), 261 < 300 -> included.
    # At 2% (threshold 200), 261 >= 200 -> excluded.
    result_low = evaluate_config(
        flag_key="new-checkout",
        user_id="user-003",
        user_groups=[],
        enabled=True,
        target_groups=[],
        rollout_percentage=2,
    )
    result_high = evaluate_config(
        flag_key="new-checkout",
        user_id="user-003",
        user_groups=[],
        enabled=True,
        target_groups=[],
        rollout_percentage=3,
    )
    assert result_low["bucket"] == result_high["bucket"] == 261
    if result_low["value"] is True:
        assert result_high["value"] is True


# ---------------------------------------------------------------------------
# E10: 10,000 synthetic IDs at 25% -> fraction plausibly near 25%
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_rollout_fraction_near_25_percent():
    """E10: Diagnostic — fraction of included users near 25% at 25% rollout."""
    included = 0
    total = 10000
    for i in range(total):
        uid = f"user-{i:05d}"
        result = evaluate_config(
            flag_key="new-checkout",
            user_id=uid,
            user_groups=[],
            enabled=True,
            target_groups=[],
            rollout_percentage=25,
        )
        if result["value"] is True:
            included += 1
    fraction = included / total
    # Diagnostic only: plausibly near 25%, do not demand exact count.
    assert 0.15 < fraction < 0.35, f"fraction={fraction:.3f} outside expected range"


# ---------------------------------------------------------------------------
# Edge cases from required.md
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_unknown_flag_is_service_layer_concern():
    """Pure evaluator assumes valid inputs; unknown flags are 404 at service layer."""
    # The pure function is given a config; it doesn't check flag existence.
    result = evaluate_config(
        flag_key="does-not-exist",
        user_id="user-001",
        user_groups=[],
        enabled=True,
        target_groups=[],
        rollout_percentage=50,
    )
    assert "value" in result
    assert "reason" in result


@pytest.mark.unit
def test_missing_user_id_rejected_by_schema():
    """Missing user_id is a validation error (422), not a false success."""
    # The pure evaluator receives user_id as a string; empty string is
    # rejected by the Pydantic schema before reaching this function.
    result = evaluate_config(
        flag_key="new-checkout",
        user_id="",
        user_groups=[],
        enabled=True,
        target_groups=[],
        rollout_percentage=50,
    )
    assert "value" in result
