"""Example script demonstrating the Python feature flag client.

This module. Shows success and fail-closed fallback paths.

Run with:
    EVALUATION_API_KEY=<key> python client/example.py

Never hardcode credentials. The evaluation API key is read from the
environment only.
"""

from __future__ import annotations

import os
import sys

from feature_flag_client import FeatureFlagClient


def main() -> int:
    base_url = os.environ.get("FEATURE_FLAG_BASE_URL", "http://localhost:8000")
    api_key = os.environ.get("EVALUATION_API_KEY")

    if not api_key:
        print("ERROR: EVALUATION_API_KEY environment variable is required.")
        print("Set it to the client evaluation key (never hardcode secrets).")
        return 1

    with FeatureFlagClient(base_url, api_key) as client:
        # Success path: seeded flag, staging, 25% rollout, user-003 (bucket 261).
        result = client.evaluate(
            flag_key="new-checkout",
            environment="staging",
            user_id="user-003",
            groups=[],
        )
        print("Success path (user-003, staging, 25% rollout):")
        print(f"  value={result['value']} reason={result['reason']} "
              f"bucket={result.get('bucket')} fallback={result['fallback']}")

        # Group match path: beta user in staging.
        result = client.evaluate(
            flag_key="new-checkout",
            environment="staging",
            user_id="user-001",
            groups=["beta"],
        )
        print("Group match (user-001, beta group):")
        print(f"  value={result['value']} reason={result['reason']} "
              f"fallback={result['fallback']}")

        # Disabled production: user-003 gets false even though bucket 261
        # would be included at 25% in staging.
        result = client.evaluate(
            flag_key="new-checkout",
            environment="production",
            user_id="user-003",
            groups=[],
        )
        print("Disabled production (user-003):")
        print(f"  value={result['value']} reason={result['reason']} "
              f"fallback={result['fallback']}")

        # Fallback path: service unreachable -> CLIENT_FALLBACK.
        with FeatureFlagClient("http://127.0.0.1:1", api_key, timeout=0.5) as bad:
            result = bad.evaluate(
                flag_key="new-checkout",
                environment="staging",
                user_id="user-003",
                groups=[],
            )
        print("Service unreachable (fail-closed fallback):")
        print(f"  value={result['value']} reason={result['reason']} "
              f"fallback={result['fallback']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
