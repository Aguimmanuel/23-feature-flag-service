"""Evaluation service: joined configuration read + pure evaluator.

This module. It retrieves active flag/config using one joined
read (via Role A's repository interface), distinguishes the documented
404 cases, calls the pure evaluator, and builds the API response. No
audit write during evaluation.

Depends on Role A's repository interface:
    app.repositories.flags.get_flag_with_environment(session, key, env)
    -> (Flag | None, FlagEnvironment | None)
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.domain.evaluator import evaluate_config
from app.repositories.flags import get_flag_with_environment


class FlagNotFoundError(Exception):
    """Raised when the flag is unknown or archived."""


class EnvironmentConfigNotFoundError(Exception):
    """Raised when the environment has no configuration row."""


def evaluate_flag(
    session: Session,
    flag_key: str,
    environment: str,
    user_id: str,
    user_groups: list[str],
) -> dict[str, object]:
    """Evaluate a flag for a user in an environment.

    Performs one joined SELECT to distinguish an unknown/archived flag
    from a missing environment configuration, then delegates to the pure
    evaluator.

    Args:
        session: SQLAlchemy session injected by the caller.
        flag_key: The feature flag key.
        environment: One of development, staging, production.
        user_id: The synthetic user identifier.
        user_groups: Groups supplied by the caller for this user.

    Returns:
        {"value": bool, "reason": str, "bucket": Optional[int]}

    Raises:
        FlagNotFoundError: flag is missing or archived.
        EnvironmentConfigNotFoundError: environment config row missing.
    """
    flag, config = get_flag_with_environment(session, flag_key, environment)

    if flag is None or flag.archived:
        raise FlagNotFoundError(flag_key)

    if config is None:
        raise EnvironmentConfigNotFoundError(flag_key, environment)

    return evaluate_config(
        flag_key=flag_key,
        user_id=user_id,
        user_groups=list(user_groups),
        enabled=config.enabled,
        target_groups=list(config.target_groups or []),
        rollout_percentage=config.rollout_percentage,
    )
