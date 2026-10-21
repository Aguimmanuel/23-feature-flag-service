"""Pure evaluation engine for feature flags.

This module. It is a pure Python function with no database,
network, clock, or secret dependencies. Same inputs always produce the
same output — deterministic rollout, not per-request randomness.

Normative resolution order (api-contract.md section 5):
  1. Invalid context -> rejected by the caller (HTTP 422), before this
     function is invoked.
  2. Missing/archived flag -> 404 FLAG_NOT_FOUND (service layer).
  3. Missing configuration -> 404 ENVIRONMENT_CONFIG_NOT_FOUND
     (service layer).
  4. enabled == false -> FLAG_DISABLED, value=false, bucket=null.
  5. Any exact group match -> GROUP_MATCH, value=true, bucket=null.
  6. Otherwise compute the percentage bucket:
     bucket < rollout_percentage * 100  -> ROLLOUT_INCLUDED (true)
     otherwise                          -> ROLLOUT_EXCLUDED (false)

Group matching and percentage inclusion are OR conditions. The disabled
switch overrides both.

Bucket algorithm:
  SHA-256(UTF-8(flag_key + ":" + user_id))
  take first 8 hex chars, interpret as unsigned base-16 integer,
  modulo 10000 -> bucket in 0..9999.

Reference vectors (must hold):
  new-checkout / user-001 -> bucket 5415
  new-checkout / user-002 -> bucket 5933
  new-checkout / user-003 -> bucket 261
"""

from __future__ import annotations

import hashlib
from typing import Optional


def compute_bucket(flag_key: str, user_id: str) -> int:
    """Compute a deterministic rollout bucket in 0..9999 for a flag/user.

    The bucket is stable for the same flag_key/user_id pair across
    environments and across requests. It does not depend on environment,
    random seed, Python's built-in hash(), time, or group names.

    Args:
        flag_key: The feature flag key (lowercase, validated upstream).
        user_id: The synthetic user identifier (validated upstream).

    Returns:
        Integer bucket in the range 0..9999.
    """
    encoded = (flag_key + ":" + user_id).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    first_eight = digest[:8]
    return int(first_eight, 16) % 10000


def evaluate_config(
    flag_key: str,
    user_id: str,
    user_groups: list[str],
    enabled: bool,
    target_groups: list[str],
    rollout_percentage: int,
) -> dict[str, object]:
    """Evaluate whether a feature flag is enabled for a user.

    Assumes inputs are already validated by the API layer. Returns a dict
    with keys value, reason, bucket.

    Args:
        flag_key: The feature flag key.
        user_id: The synthetic user identifier.
        user_groups: Groups supplied by the caller for this user.
        enabled: Whether the flag is enabled in the target environment.
        target_groups: Groups configured for this environment.
        rollout_percentage: Integer 0..100 rollout for this environment.

    Returns:
        {"value": bool, "reason": str, "bucket": Optional[int]}
        - bucket is None for FLAG_DISABLED and GROUP_MATCH decisions.
        - bucket is an int 0..9999 for ROLLOUT_INCLUDED / ROLLOUT_EXCLUDED.
    """
    # Step 4: disabled overrides all inclusion paths.
    if not enabled:
        return {"value": False, "reason": "FLAG_DISABLED", "bucket": None}

    # Step 5: exact, case-sensitive group intersection (OR condition).
    # An empty target_group list matches nobody.
    if set(user_groups) & set(target_groups):
        return {"value": True, "reason": "GROUP_MATCH", "bucket": None}

    # Step 6: deterministic percentage rollout.
    bucket = compute_bucket(flag_key, user_id)
    threshold = rollout_percentage * 100

    if bucket < threshold:
        return {"value": True, "reason": "ROLLOUT_INCLUDED", "bucket": bucket}

    return {"value": False, "reason": "ROLLOUT_EXCLUDED", "bucket": bucket}
