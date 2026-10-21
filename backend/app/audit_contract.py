"""Audit integration interface. The implementation belongs to the audit service."""

from importlib import import_module
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas import Environment


class AuditWriter(Protocol):
    def __call__(
        self, session: Session, flag_id: UUID, environment: Environment | None,
        action: str, actor: str, before_state: dict | None, after_state: dict,
    ) -> None: ...


class AuditWriterUnavailable(RuntimeError):
    pass


def load_audit_writer() -> AuditWriter:
    try:
        module = import_module("app.services.audit")
    except ModuleNotFoundError as exc:
        if exc.name != "app.services.audit":
            raise
        raise AuditWriterUnavailable("The transactional audit writer is not integrated") from None
    writer = getattr(module, "record_change", None)
    if not callable(writer):
        raise AuditWriterUnavailable("The transactional record_change interface is unavailable")
    return writer
