"""Explicit, atomic seed command. Existing flag keys are left unchanged."""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.audit_contract import AuditWriter, AuditWriterUnavailable, load_audit_writer
from app.config import Settings
from app.db import create_database_engine, create_session_factory
from app.models import Flag, FlagEnvironment
from app.schemas import ENVIRONMENTS

SEED_LOCK_ID = 62394102


@dataclass(frozen=True)
class SeedResult:
    created: tuple[str, ...]
    skipped: tuple[str, ...]


def seed_database(factory: sessionmaker[Session], writer: AuditWriter) -> SeedResult:
    created, skipped = [], []
    with factory() as session, session.begin():
        # Serialize concurrent seed commands; a rerun must not reset demo edits.
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SEED_LOCK_ID})
        for key, description in (
            ("new-checkout", "New checkout experiment"),
            ("search-preview", "Search preview experiment"),
        ):
            existing = session.scalar(select(Flag).where(Flag.key == key).with_for_update())
            if existing is not None:
                skipped.append(key)
                continue
            flag = Flag(key=key, description=description)
            session.add(flag)
            session.flush()
            for environment in ENVIRONMENTS:
                enabled, groups, rollout = False, [], 0
                if key == "new-checkout" and environment == "development":
                    enabled, rollout = True, 100
                elif key == "new-checkout" and environment == "staging":
                    enabled, groups, rollout = True, ["beta"], 25
                session.add(FlagEnvironment(
                    flag_id=flag.id, environment=environment, enabled=enabled,
                    target_groups=groups, rollout_percentage=rollout, version=1,
                ))
            session.flush()
            writer(
                session=session, flag_id=flag.id, environment=None, action="FLAG_CREATED",
                actor="seed", before_state=None,
                after_state={"key": flag.key, "description": flag.description, "archived": False},
            )
            session.flush()
            created.append(key)
    return SeedResult(tuple(created), tuple(skipped))


def main() -> None:
    try:
        writer = load_audit_writer()
    except AuditWriterUnavailable as exc:
        raise SystemExit(str(exc)) from None
    settings = Settings()
    if settings.app_env == "test":
        raise SystemExit("Use the verified test harness for test-database seeds")
    engine = create_database_engine(settings)
    try:
        result = seed_database(create_session_factory(engine), writer)
        print("Created: " + (", ".join(result.created) or "none"))
        print("Skipped existing keys: " + (", ".join(result.skipped) or "none"))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
