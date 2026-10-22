"""Validated server configuration. No credentials have default values."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr
    admin_token: SecretStr
    evaluation_api_key: SecretStr
    app_env: Literal["development", "test", "production"] = "development"
    allowed_origins: str = ""
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = (
                url.drivername in {"postgresql", "postgresql+psycopg"}
                and bool(url.host)
                and bool(url.database)
                and bool(url.username)
            )
            # Accessing port also validates its representation.
            _ = url.port
        except (ArgumentError, ValueError):
            valid = False
        if not valid:
            raise ValueError("A valid PostgreSQL connection URL is required")
        return value

    @field_validator("admin_token", "evaluation_api_key")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if (
            not secret
            or secret != secret.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in secret)
            or secret.startswith("REPLACE_WITH_")
        ):
            raise ValueError("Set a nonempty secret without whitespace padding or controls")
        return value

    @model_validator(mode="after")
    def validate_distinct_secrets(self) -> "Settings":
        if self.admin_token.get_secret_value() == self.evaluation_api_key.get_secret_value():
            raise ValueError("Admin and evaluation credentials must be different")
        return self

    @property
    def cors_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]
        if "*" in origins or any(
            not origin.startswith(("http://", "https://")) for origin in origins
        ):
            raise ValueError("Configure explicit HTTP(S) frontend origins; wildcard is forbidden")
        return origins
