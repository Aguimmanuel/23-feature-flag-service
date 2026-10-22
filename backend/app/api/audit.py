"""Read-only audit history using the shared authentication, models and schemas."""

from datetime import datetime, timezone
from typing import Any, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import InterfaceError

from app.auth import require_admin
from app.db import SessionDependency
from app.errors import APIError
from app.models import AuditLog, Flag
from app.schemas import AuditPage, FlagKey
from app.services.audit import AuditValidationError, validate_change

router = APIRouter(
    prefix="/api/v1/flags", tags=["Audit"],
    dependencies=[Depends(require_admin)],
)


def serialize_entry(row: Any, flag_key: str) -> dict[str, Any]:
    """Project contract fields only; fail closed on corrupt stored snapshots."""
    _, before, after = validate_change(
        row.flag_id, row.environment, row.action, row.actor,
        row.before_state, row.after_state,
    )
    if row.action != "CONFIG_UPDATED" and after["key"] != flag_key:
        raise AuditValidationError("Audit key does not match its flag")
    timestamp = row.created_at
    if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
        raise AuditValidationError("Invalid audit timestamp")
    try:
        identifier = str(UUID(str(row.id)))
    except (TypeError, ValueError, AttributeError):
        raise AuditValidationError("Invalid audit identifier") from None
    return {
        "id": identifier, "flag_key": flag_key, "environment": row.environment,
        "action": row.action, "actor": row.actor, "before": before, "after": after,
        "created_at": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@router.get("/{key}/audit", response_model=AuditPage)
def list_audit(
    key: FlagKey,
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    try:
        # No archived=false filter: archival never removes history access.
        flag_id = session.scalar(select(Flag.id).where(Flag.key == key))
        if flag_id is None:
            raise APIError(404, "FLAG_NOT_FOUND", "Flag was not found")
        total = session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.flag_id == flag_id)
        )
        rows = session.execute(
            select(AuditLog, Flag.key)
            .join(Flag, Flag.id == AuditLog.flag_id)
            .where(AuditLog.flag_id == flag_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit).offset(offset)
        ).all()
        return {
            "items": [serialize_entry(row, stored_key) for row, stored_key in rows],
            "total": int(total or 0), "limit": limit, "offset": offset,
        }
    except InterfaceError:
        raise APIError(503, "SERVICE_UNAVAILABLE", "Database service is unavailable") from None
    # Shared handlers sanitize validation, operational/pool errors, corrupt
    # snapshots and unexpected errors. No commits, audit writes or input logging.
