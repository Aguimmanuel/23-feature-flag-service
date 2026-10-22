"""Evaluation endpoints: POST /api/v1/evaluate and POST /api/v1/admin/evaluate.

Both routes use the same service function,
request shape, and successful response. They differ only in the
credential checked:

- POST /api/v1/evaluate        -> X-API-Key: <EVALUATION_API_KEY>
- POST /api/v1/admin/evaluate  -> Authorization: Bearer <ADMIN_TOKEN>

Request (documented in README.md):
    {"flag_key": "...", "environment": "...", "user": {"id": "...", "groups": []}}

Response:
    {"flag_key": "...", "environment": "...", "value": true, "reason": "...", "bucket": 261}

Normative resolution order is enforced by the evaluation service:
  1. Auth + validation (422 on invalid context)
  2. Missing/archived flag -> 404 FLAG_NOT_FOUND
  3. Missing config -> 404 ENVIRONMENT_CONFIG_NOT_FOUND
  4. enabled=false -> FLAG_DISABLED
  5. Group match -> GROUP_MATCH
  6. Percentage rollout -> ROLLOUT_INCLUDED / ROLLOUT_EXCLUDED

No per-evaluation audit writes. No configuration cache.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth import require_admin, require_evaluation_key
from app.db import SessionDependency
from app.errors import APIError
from app.services.evaluation import (
    EnvironmentConfigNotFoundError,
    FlagNotFoundError,
    evaluate_flag,
)
from app.schemas import (
    EvaluationRequest,
    EvaluationResponse,
    ErrorEnvelope,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared evaluation logic
# ---------------------------------------------------------------------------


def _evaluate(
    body: EvaluationRequest,
    session: SessionDependency,
) -> EvaluationResponse:
    """Core evaluation used by both client and admin routes."""
    try:
        result = evaluate_flag(
            session=session,
            flag_key=body.flag_key,
            environment=body.environment,
            user_id=body.user.id,
            user_groups=body.user.groups,
        )
    except FlagNotFoundError:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="FLAG_NOT_FOUND",
            message="Flag not found",
        )
    except EnvironmentConfigNotFoundError:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="ENVIRONMENT_CONFIG_NOT_FOUND",
            message="Environment configuration not found",
        )

    return EvaluationResponse(
        flag_key=body.flag_key,
        environment=body.environment,
        value=result["value"],  # type: ignore[index]
        reason=result["reason"],  # type: ignore[index]
        bucket=result["bucket"],  # type: ignore[index]
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
        503: {"model": ErrorEnvelope},
    },
    tags=["evaluation"],
)
def client_evaluate(
    body: EvaluationRequest,
    session: SessionDependency,
    _: None = Depends(require_evaluation_key),
) -> EvaluationResponse:
    """Client evaluation endpoint. Authenticated with X-API-Key.

    External clients call this route. The evaluation key must never be
    placed in the frontend build.
    """
    return _evaluate(body, session)


@router.post(
    "/admin/evaluate",
    response_model=EvaluationResponse,
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
        503: {"model": ErrorEnvelope},
    },
    tags=["evaluation"],
)
def admin_evaluate(
    body: EvaluationRequest,
    session: SessionDependency,
    _: None = Depends(require_admin),
) -> EvaluationResponse:
    """Admin evaluation endpoint. Authenticated with Bearer ADMIN_TOKEN.

    The dashboard tester calls this route. The admin token is entered
    manually and held in memory only.
    """
    return _evaluate(body, session)
