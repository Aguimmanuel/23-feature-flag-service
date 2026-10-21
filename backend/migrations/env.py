"""Migrate the configured development/release database or a verified test connection."""

from alembic import context

from app.config import Settings
from app.db import create_database_engine
from app.models import Base

config = context.config
target_metadata = Base.metadata


def run_with_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        dialect_name="postgresql", target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        # Test harness verifies identity and server version before supplying this.
        run_with_connection(supplied_connection)
    else:
        settings = Settings()
        if settings.app_env == "test":
            raise RuntimeError("Use the verified test harness to migrate the test database")
        engine = create_database_engine(settings)
        try:
            with engine.connect() as connection:
                run_with_connection(connection)
        finally:
            engine.dispose()
