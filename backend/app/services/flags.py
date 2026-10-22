"""Flag management transactions. Audit writes participate in the same commit."""

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_contract import AuditWriter, AuditWriterUnavailable, load_audit_writer
from app.errors import APIError
from app.models import Flag, FlagEnvironment
from app.schemas import (
    ENVIRONMENTS, Environment, EnvironmentResponse, EnvironmentUpdate,
    FlagCreate, FlagDetail, FlagPage, FlagSummary, FlagUpdate,
)


def get_audit_writer() -> AuditWriter:
    try:
        return load_audit_writer()
    except AuditWriterUnavailable:
        raise APIError(503, "SERVICE_UNAVAILABLE", "Transactional audit service is not integrated") from None


def _active_flag(session: Session, key: str, *, lock: bool = False) -> Flag:
    statement = select(Flag).where(Flag.key == key)
    if lock:
        statement = statement.with_for_update()
    flag = session.scalar(statement)
    if flag is None or flag.archived:
        raise APIError(404, "FLAG_NOT_FOUND", "Flag was not found")
    return flag


def _flag_snapshot(flag: Flag) -> dict:
    return {"key": flag.key, "description": flag.description, "archived": flag.archived}


def _config_snapshot(config: EnvironmentResponse) -> dict:
    return config.model_dump(include={"enabled", "target_groups", "rollout_percentage", "version"})


def _detail(flag: Flag) -> FlagDetail:
    values = FlagSummary.model_validate(flag).model_dump()
    configs = sorted(flag.environments, key=lambda item: ENVIRONMENTS.index(item.environment))
    return FlagDetail(**values, environments=[EnvironmentResponse.model_validate(item) for item in configs])


def list_flags(session: Session, limit: int, offset: int) -> FlagPage:
    count = session.scalar(select(func.count()).select_from(Flag).where(Flag.archived.is_(False)))
    flags = session.scalars(
        select(Flag).where(Flag.archived.is_(False)).order_by(Flag.key).limit(limit).offset(offset)
    ).all()
    return FlagPage(items=[FlagSummary.model_validate(flag) for flag in flags], total=count, limit=limit, offset=offset)


def get_flag(session: Session, key: str) -> FlagDetail:
    return _detail(_active_flag(session, key))


def create_flag(session: Session, data: FlagCreate, writer: AuditWriter) -> FlagDetail:
    try:
        with session.begin():
            flag = Flag(key=data.key, description=data.description)
            session.add(flag)
            session.flush()
            flag.environments = [FlagEnvironment(environment=environment) for environment in ENVIRONMENTS]
            session.flush()
            writer(
                session=session, flag_id=flag.id, environment=None, action="FLAG_CREATED",
                actor="shared-admin", before_state=None, after_state=_flag_snapshot(flag),
            )
            session.flush()
            result = _detail(flag)
        return result
    except IntegrityError as exc:
        original = exc.orig
        constraint = getattr(getattr(original, "diag", None), "constraint_name", None)
        if getattr(original, "sqlstate", None) == "23505" and constraint == "flags_key_key":
            raise APIError(409, "FLAG_KEY_CONFLICT", "Flag key is already reserved") from None
        raise


def update_description(session: Session, key: str, data: FlagUpdate, writer: AuditWriter) -> FlagDetail:
    with session.begin():
        flag = _active_flag(session, key, lock=True)
        before = _flag_snapshot(flag)
        flag.description = data.description
        flag.updated_at = datetime.now(timezone.utc)
        writer(
            session=session, flag_id=flag.id, environment=None, action="FLAG_UPDATED",
            actor="shared-admin", before_state=before, after_state=_flag_snapshot(flag),
        )
        session.flush()
        result = _detail(flag)
    return result


def update_environment(
    session: Session, key: str, environment: Environment,
    data: EnvironmentUpdate, writer: AuditWriter,
) -> EnvironmentResponse:
    with session.begin():
        flag = _active_flag(session, key, lock=True)
        previous = session.get(FlagEnvironment, (flag.id, environment))
        if previous is None:
            raise APIError(404, "ENVIRONMENT_CONFIG_NOT_FOUND", "Environment configuration was not found")
        before = EnvironmentResponse.model_validate(previous)
        now = datetime.now(timezone.utc)
        row = session.execute(
            update(FlagEnvironment)
            .where(
                FlagEnvironment.flag_id == flag.id,
                FlagEnvironment.environment == environment,
                FlagEnvironment.version == data.version,
            )
            .values(
                enabled=data.enabled, target_groups=data.sorted_target_groups(),
                rollout_percentage=data.rollout_percentage,
                version=FlagEnvironment.version + 1, updated_at=now,
            )
            .returning(*FlagEnvironment.__table__.columns)
            .execution_options(synchronize_session=False)
        ).mappings().one_or_none()
        if row is None:
            raise APIError(409, "VERSION_CONFLICT", "Configuration version is stale; reload before saving")
        result = EnvironmentResponse.model_validate(dict(row))
        flag.updated_at = now
        writer(
            session=session, flag_id=flag.id, environment=environment, action="CONFIG_UPDATED",
            actor="shared-admin", before_state=_config_snapshot(before), after_state=_config_snapshot(result),
        )
        session.flush()
    return result


def archive_flag(session: Session, key: str, writer: AuditWriter) -> None:
    with session.begin():
        flag = _active_flag(session, key, lock=True)
        before = _flag_snapshot(flag)
        flag.archived = True
        flag.updated_at = datetime.now(timezone.utc)
        writer(
            session=session, flag_id=flag.id, environment=None, action="FLAG_ARCHIVED",
            actor="shared-admin", before_state=before, after_state=_flag_snapshot(flag),
        )
        session.flush()
