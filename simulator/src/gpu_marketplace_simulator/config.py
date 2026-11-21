from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIMULATOR_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    manager_dispatch_token: SecretStr | None = Field(default=None, repr=False)
    dispatch_max_body_bytes: int | None = Field(default=None, gt=0)

    @field_validator("manager_dispatch_token")
    @classmethod
    def require_dispatch_token_minimum_length(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("manager dispatch token must contain at least 32 bytes")
        return value

    @field_validator("dispatch_max_body_bytes", mode="before")
    @classmethod
    def reject_non_integer_body_limit(cls, value: object) -> object:
        if type(value) in (bool, float):
            raise ValueError("dispatch body limit must be an integer")
        return value
