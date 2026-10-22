"""Management endpoints. Evaluation and audit routes are separate components."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.audit_contract import AuditWriter
from app.auth import require_admin
from app.db import SessionDependency
from app.schemas import (
    Environment, EnvironmentResponse, EnvironmentUpdate, FlagCreate, FlagDetail,
    FlagKey, FlagPage, FlagUpdate,
)
from app.services import flags as service

router = APIRouter(prefix="/api/v1/flags", tags=["Flags"], dependencies=[Depends(require_admin)])
AuditDependency = Annotated[AuditWriter, Depends(service.get_audit_writer)]


@router.post("", response_model=FlagDetail, status_code=201)
def create(data: FlagCreate, session: SessionDependency, writer: AuditDependency, response: Response):
    result = service.create_flag(session, data, writer)
    response.headers["Location"] = f"/api/v1/flags/{result.key}"
    return result


@router.get("", response_model=FlagPage)
def list_all(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return service.list_flags(session, limit, offset)


@router.get("/{key}", response_model=FlagDetail)
def detail(key: FlagKey, session: SessionDependency):
    return service.get_flag(session, key)


@router.patch("/{key}", response_model=FlagDetail)
def update_description(key: FlagKey, data: FlagUpdate, session: SessionDependency, writer: AuditDependency):
    return service.update_description(session, key, data, writer)


@router.put("/{key}/environments/{environment}", response_model=EnvironmentResponse)
def update_environment(
    key: FlagKey, environment: Environment, data: EnvironmentUpdate,
    session: SessionDependency, writer: AuditDependency,
):
    return service.update_environment(session, key, environment, data, writer)


@router.delete("/{key}", status_code=204)
def archive(key: FlagKey, session: SessionDependency, writer: AuditDependency):
    service.archive_flag(session, key, writer)
    return Response(status_code=204)
