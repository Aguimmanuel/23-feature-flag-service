"""Flag repository queries.

This module. It provides the joined flag + environment read
used by the evaluation service.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models import Flag, FlagEnvironment


def get_flag_with_environment(
    session: Session, key: str, environment: str
) -> tuple[Flag | None, FlagEnvironment | None]:
    """Return (flag, config) for a flag key and environment.

    Uses a single joined SELECT so the caller can distinguish an
    unknown/archived flag from a missing environment configuration row.
    """
    flag = (
        session.query(Flag)
        .options(joinedload(Flag.environments))
        .filter(Flag.key == key)
        .one_or_none()
    )
    if flag is None:
        return None, None

    config = None
    for env in flag.environments:
        if env.environment == environment:
            config = env
            break

    return flag, config
