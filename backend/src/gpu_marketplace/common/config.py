from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GPU_MARKETPLACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = (
        "postgresql+psycopg://gpu_marketplace:local-dev-only-change-me@localhost:5432/gpu_marketplace"
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    log_level: LogLevel = "INFO"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
        except Exception as exc:
            raise ValueError("database URL is invalid") from exc
        if url.drivername != "postgresql+psycopg":
            raise ValueError("database URL must use the approved postgresql+psycopg driver")
        if not url.host or not url.database:
            raise ValueError("database URL must include a host and database name")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("at least one local CORS origin must be configured")
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
                raise ValueError("CORS origins must be HTTP(S) origins without a path")
        return origins
