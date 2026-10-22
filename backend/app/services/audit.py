"""Transactional audit writer for feature-flag change history.

The caller owns the SQLAlchemy session and transaction. This module creates no
engine, table, model, migration, commit, rollback, or independent transaction.
Uses the shared ``app.models.AuditLog`` model already present in the backend.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import UUID, uuid4
import re

Action = Literal["FLAG_CREATED", "FLAG_UPDATED", "CONFIG_UPDATED", "FLAG_ARCHIVED"]
Environment = Literal["development", "staging", "production"]
Actor = Literal["shared-admin", "seed"]
Snapshot = dict[str, Any]

_ACTIONS = frozenset({"FLAG_CREATED", "FLAG_UPDATED", "CONFIG_UPDATED", "FLAG_ARCHIVED"})
_ENVIRONMENTS = frozenset({"development", "staging", "production"})
_FLAG_FIELDS = frozenset({"key", "description", "archived"})
_CONFIG_FIELDS = frozenset({"enabled", "target_groups", "rollout_percentage", "version"})
_KEY = re.compile(r"[a-z][a-z0-9_-]{0,63}")


class AuditValidationError(ValueError):
    """A caller supplied a non-contract event. Messages never echo input values."""


class AuditModelUnavailable(RuntimeError):
    """The shared ORM model could not be imported; never substitute a fake model."""


class AuditSession(Protocol):
    def add(self, instance: object) -> None: ...

    def flush(self) -> None: ...


def _load_audit_model() -> Any:
    # One explicit integration adapter, NOT a second mapped class/schema.
    # This class is the verified model from the shared integration base.
    try:
        from app.models import AuditLog
    except ImportError:
        raise AuditModelUnavailable("The shared audit model is not available") from None
    return AuditLog


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if type(value) is str:
        try:
            return UUID(value)
        except ValueError:
            pass
    raise AuditValidationError("Invalid audit identifier")


def _snapshot(value: object, *, configuration: bool) -> Snapshot:
    expected = _CONFIG_FIELDS if configuration else _FLAG_FIELDS
    if type(value) is not dict or set(value) != expected:
        raise AuditValidationError("Invalid audit snapshot fields")

    if configuration:
        if type(value["enabled"]) is not bool:
            raise AuditValidationError("Invalid audit enabled state")
        percentage = value["rollout_percentage"]
        version = value["version"]
        if type(percentage) is not int or not 0 <= percentage <= 100:
            raise AuditValidationError("Invalid audit rollout percentage")
        if type(version) is not int or version < 1:
            raise AuditValidationError("Invalid audit version")
        groups = value["target_groups"]
        if type(groups) is not list or len(groups) > 20:
            raise AuditValidationError("Invalid audit groups")
        for group in groups:
            if (
                type(group) is not str
                or not 1 <= len(group) <= 64
                or group != group.strip()
                or any(ord(character) < 32 or ord(character) == 127 for character in group)
            ):
                raise AuditValidationError("Invalid audit groups")
        if len(set(groups)) != len(groups):
            raise AuditValidationError("Invalid audit groups")
        # Fresh containers prevent later mutation of the caller's objects.
        return {
            "enabled": value["enabled"],
            "target_groups": sorted(groups),
            "rollout_percentage": percentage,
            "version": version,
        }

    key, description, archived = value["key"], value["description"], value["archived"]
    if type(key) is not str or _KEY.fullmatch(key) is None:
        raise AuditValidationError("Invalid audit flag key")
    if type(description) is not str or len(description) > 500:
        raise AuditValidationError("Invalid audit description")
    if type(archived) is not bool:
        raise AuditValidationError("Invalid audit archived state")
    return {"key": key, "description": description, "archived": archived}


def validate_change(
    flag_id: object,
    environment: object,
    action: object,
    actor: object,
    before_state: object,
    after_state: object,
) -> tuple[UUID, Snapshot | None, Snapshot]:
    """Validate and copy only documented snapshot fields, without any DB access.

    This allowlist excludes headers/tokens as *extra fields*. It cannot detect a
    secret somebody puts inside an otherwise valid description or group name.
    Callers must not pass credentials in those free-text fields either.
    """
    identifier = _uuid(flag_id)
    if type(action) is not str or action not in _ACTIONS:
        raise AuditValidationError("Invalid audit action")
    if type(actor) is not str or actor not in {"shared-admin", "seed"}:
        raise AuditValidationError("Invalid audit actor")
    if actor == "seed" and action != "FLAG_CREATED":
        raise AuditValidationError("Seed actor is only valid for flag creation")

    configuration = action == "CONFIG_UPDATED"
    if configuration:
        if type(environment) is not str or environment not in _ENVIRONMENTS:
            raise AuditValidationError("Invalid audit environment")
    elif environment is not None:
        raise AuditValidationError("Flag-level audit environment must be null")

    after = _snapshot(after_state, configuration=configuration)
    if action == "FLAG_CREATED":
        if before_state is not None or after["archived"] is not False:
            raise AuditValidationError("Invalid flag creation snapshots")
        return identifier, None, after

    before = _snapshot(before_state, configuration=configuration)
    if configuration:
        if after["version"] != before["version"] + 1:
            raise AuditValidationError("Invalid audit version transition")
    else:
        if before["key"] != after["key"] or before["archived"] is not False:
            raise AuditValidationError("Invalid flag audit transition")
        if action == "FLAG_UPDATED" and after["archived"] is not False:
            raise AuditValidationError("Invalid flag update snapshots")
        if action == "FLAG_ARCHIVED" and (
            after["archived"] is not True or before["description"] != after["description"]
        ):
            raise AuditValidationError("Invalid flag archive snapshots")
    return identifier, before, after


def record_change(
    session: AuditSession,
    flag_id: UUID | str,
    environment: Environment | None,
    action: Action,
    actor: Actor,
    before_state: Snapshot | None,
    after_state: Snapshot,
) -> None:
    """Add and flush one real shared-model row in the caller's transaction.

    Call exactly once per successful business mutation and before its commit.
    Do not call during evaluation or for rejected requests. A successful
    configuration PUT with unchanged values still needs a versioned event.

    Flush exceptions deliberately propagate. The owning service MUST roll back
    its business mutation when this function fails; it must not catch and commit.
    Returning successfully is not a commit and does not prove durability.
    """
    identifier, before, after = validate_change(
        flag_id, environment, action, actor, before_state, after_state
    )
    model = _load_audit_model()
    row = model(
        id=uuid4(),
        flag_id=identifier,
        environment=environment,
        action=action,
        actor=actor,
        before_state=before,
        after_state=after,
    )
    session.add(row)
    # Flush ALL pending business/audit changes, including a new parent flag.
    # Never use a separate Session, commit(), rollback(), or begin_nested() here.
    session.flush()
