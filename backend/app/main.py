"""Application assembly. No migrations, seeds, or database reads at startup."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.evaluation import router as evaluation_router
from app.api.flags import router as flags_router
from app.config import Settings
from app.db import create_database_engine, create_session_factory
from app.errors import register_error_handlers
from app.middleware import BodySizeLimitMiddleware, ConfiguredCORSMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
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

    app = FastAPI(title="Feature Flag Service", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(ConfiguredCORSMiddleware)
    app.include_router(flags_router)
    app.include_router(evaluation_router, prefix="/api/v1")
    register_error_handlers(app)
    return app


app = create_app()
