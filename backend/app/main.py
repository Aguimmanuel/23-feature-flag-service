"""Application assembly. No migrations, seeds, or database reads at startup."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.audit import router as audit_router
from app.api.evaluation import router as evaluation_router
from app.api.flags import router as flags_router
from app.api.health import router as health_router
from app.config import Settings
from app.db import create_database_engine, create_session_factory
from app.errors import register_error_handlers
from app.middleware import BodySizeLimitMiddleware, ConfiguredCORSMiddleware
from app.services.static_frontend import mount_frontend
from app.schemas import ErrorEnvelope

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(
    settings: Settings | None = None, *, frontend_directory: str | Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configured = settings or Settings()
        # Validate CORS before starting, even when there are no business routes yet.
        configured.cors_origins
        engine = create_database_engine(configured)
        app.state.settings = configured
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Feature Flag Service", version="0.1.0", lifespan=lifespan,
        responses={code: {"model": ErrorEnvelope} for code in (401, 404, 409, 413, 422, 500, 503)},
    )
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(ConfiguredCORSMiddleware)
    app.include_router(flags_router)
    app.include_router(evaluation_router, prefix="/api/v1")
    app.include_router(audit_router)
    app.include_router(health_router)
    register_error_handlers(app)
    # Preserve API-only development while the frontend owner completes the UI.
    # An explicit directory must be valid; an available real production build
    # is mounted last and cannot swallow API/health errors or missing assets.
    built_frontend = Path(frontend_directory) if frontend_directory is not None else PROJECT_ROOT / "frontend" / "dist"
    if frontend_directory is not None or (built_frontend / "index.html").is_file():
        mount_frontend(app, built_frontend)
    return app


app = create_app()
