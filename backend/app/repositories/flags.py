"""Single-read lookup for an active flag and its requested environment."""

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Flag, FlagEnvironment


def get_flag_with_environment(
    session: Session, key: str, environment: str,
) -> tuple[Flag | None, FlagEnvironment | None]:
    statement = (
        select(Flag, FlagEnvironment)
        .outerjoin(FlagEnvironment, and_(
            FlagEnvironment.flag_id == Flag.id,
            FlagEnvironment.environment == environment,
        ))
        .where(Flag.key == key, Flag.archived.is_(False))
    )
    row = session.execute(statement).one_or_none()
    return (row[0], row[1]) if row is not None else (None, None)
