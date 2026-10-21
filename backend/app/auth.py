"""Separate credentials for management and external evaluation routes."""

import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.errors import APIError

bearer_scheme = HTTPBearer(auto_error=False)
evaluation_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _matches(supplied: str, expected: str) -> bool:
    return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if credentials is None or not _matches(
        credentials.credentials, settings.admin_token.get_secret_value()
    ):
        raise APIError(401, "UNAUTHORIZED", "Authentication required")


def require_evaluation_key(
    key: Annotated[str | None, Depends(evaluation_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if key is None or not _matches(key, settings.evaluation_api_key.get_secret_value()):
        raise APIError(401, "UNAUTHORIZED", "Authentication required")
