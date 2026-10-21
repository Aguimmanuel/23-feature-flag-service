import secrets

import pytest

from app.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test_user@127.0.0.1:5432/feature_flags_dev",
        admin_token=secrets.token_hex(32),
        evaluation_api_key=secrets.token_hex(32),
        app_env="test",
        allowed_origins="",
    )
