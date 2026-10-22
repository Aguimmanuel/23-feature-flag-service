"""Public health routes using the application's existing database engine."""

from collections.abc import Callable
from typing import Any


def make_database_probe(engine: Any) -> Callable[[], None]:
    """Read-only check; the shared engine already bounds pool/connect waits.

    db.py currently uses three-second pool/connect timeouts. The query timeout
    here is transaction-local and is reset when the connection rolls back.
    """
    def probe() -> None:
        from sqlalchemy import text
        with engine.connect() as connection:
            connection.execute(text("SELECT set_config('statement_timeout', '2000ms', true)"))
            if connection.execute(text("SELECT 1")).scalar_one() != 1:
                raise RuntimeError("Readiness check failed")
    return probe


def build_health_router(*, check_database: Callable[[], None] | None = None):
    """The optional callback is an isolated-test seam, never a runtime mock."""
    from fastapi import APIRouter, Request
    from app.errors import error_response

    health = APIRouter(prefix="/health", tags=["Health"])

    @health.get("/live")
    def liveness():
        # Do not acquire a session or call the readiness callback.
        return {"status": "ok"}

    @health.get("/ready")
    def readiness(request: Request):
        try:
            probe = check_database if check_database is not None else make_database_probe(request.app.state.engine)
            probe()
        except Exception:
            return error_response(503, "SERVICE_UNAVAILABLE", "Service temporarily unavailable")
        return {"status": "ready"}

    return health


router = build_health_router()
