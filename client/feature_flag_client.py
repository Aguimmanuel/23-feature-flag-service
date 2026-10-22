"""Reusable Python client for the Feature Flag Service evaluation API.

Provides a fail-closed evaluation helper:

    evaluate(flag_key, environment, user_id, groups=None)

Behavior (documented in README.md):
  - Reusable HTTPX client with a 2-second request timeout.
  - No automatic retry loop.
  - On success: returns {value, reason, fallback=False} from the server.
  - On timeout, network error, non-2xx, or malformed result:
    returns {value=False, reason="CLIENT_FALLBACK", fallback=True}.
  - Never logs credentials.

The helper owns fail-closed fallback. The API itself never converts
missing flags or infrastructure errors into 200 false results.
"""

from __future__ import annotations

from typing import Optional
import httpx


class FeatureFlagClient:
    """Reusable client for the /api/v1/evaluate endpoint.

    Configure once with the base URL and evaluation API key. The client
    is safe to reuse across calls (connection pooling via HTTPX).
    """

    def __init__(
        self,
        base_url: str,
        evaluation_api_key: str,
        timeout: float = 2.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not evaluation_api_key:
            raise ValueError("evaluation_api_key is required")
        self._base_url = base_url.rstrip("/")
        self._api_key = evaluation_api_key
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def evaluate(
        self,
        flag_key: str,
        environment: str,
        user_id: str,
        groups: Optional[list[str]] = None,
    ) -> dict:
        """Evaluate whether a flag is enabled for a user.

        Returns a dict with keys value, reason, fallback:
          - On server success: server value/reason, fallback=False.
          - On any transport/service failure: value=False,
            reason="CLIENT_FALLBACK", fallback=True.

        Never raises for network or service failures; callers always get
        a distinguishable safe-false result.
        """
        if groups is None:
            groups = []

        payload = {
            "flag_key": flag_key,
            "environment": environment,
            "user": {"id": user_id, "groups": groups},
        }

        try:
            response = self._client.post(
                f"{self._base_url}/api/v1/evaluate",
                json=payload,
                headers={"X-API-Key": self._api_key},
            )

            # Any non-2xx is a service failure -> fail-closed fallback.
            if response.status_code != 200:
                return {
                    "value": False,
                    "reason": "CLIENT_FALLBACK",
                    "fallback": True,
                }

            data = response.json()

            if not self._valid_response(data, flag_key, environment):
                return self._fallback("malformed-response")

            return {
                "value": data["value"],
                "reason": data["reason"],
                "fallback": False,
            }

        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RequestError,
            ValueError,  # includes JSON decode errors
        ):
            return self._fallback("transport-error")

    @staticmethod
    def _valid_response(data: object, flag_key: str, environment: str) -> bool:
        """Never turn an untrusted string/number into a successful boolean."""
        if not isinstance(data, dict):
            return False
        required = {"flag_key", "environment", "value", "reason", "bucket"}
        if not required <= data.keys() or type(data["value"]) is not bool:
            return False
        if data["flag_key"] != flag_key or data["environment"] != environment:
            return False
        decisions = {
            "FLAG_DISABLED": False, "GROUP_MATCH": True,
            "ROLLOUT_INCLUDED": True, "ROLLOUT_EXCLUDED": False,
        }
        reason = data["reason"]
        if type(reason) is not str or reason not in decisions or data["value"] is not decisions[reason]:
            return False
        bucket = data["bucket"]
        if reason in {"FLAG_DISABLED", "GROUP_MATCH"}:
            return bucket is None
        return type(bucket) is int and 0 <= bucket <= 9999

    def _fallback(self, category: Optional[str] = None) -> dict:
        """Return the fail-closed fallback result.

        Optionally records a sanitized status/error category for
        diagnostics. Never includes credentials or raw error details.
        """
        result = {
            "value": False,
            "reason": "CLIENT_FALLBACK",
            "fallback": True,
        }
        if category is not None:
            # Sanitized diagnostic only; never credentials or stack traces.
            result["_diagnostic_category"] = category
        return result

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def evaluate(
    flag_key: str,
    environment: str,
    user_id: str,
    groups: Optional[list[str]] = None,
    *,
    base_url: str,
    evaluation_api_key: str,
) -> dict:
    """Convenience one-shot evaluation.

    Creates a client per call (acceptable for scripts). For repeated
    calls, instantiate FeatureFlagClient directly to reuse connections.
    """
    with FeatureFlagClient(base_url, evaluation_api_key) as client:
        return client.evaluate(flag_key, environment, user_id, groups)
