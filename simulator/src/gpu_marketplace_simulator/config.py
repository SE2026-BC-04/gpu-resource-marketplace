import base64
import binascii
import math
import re
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_CANONICAL_SERVICE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _is_canonical_service_token(token: str) -> bool:
    if _CANONICAL_SERVICE_TOKEN.fullmatch(token) is None:
        return False
    try:
        decoded = base64.b64decode(token + "=", altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        return False
    return (
        len(decoded) == 32
        and base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") == token
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIMULATOR_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    manager_dispatch_token: SecretStr | None = Field(default=None, repr=False)
    dispatch_max_body_bytes: int | None = Field(default=None, gt=0)
    attempt_cache_max_entries: int | None = Field(default=None, gt=0)
    attempt_cache_ttl_seconds: float | None = Field(default=None, gt=0)
    producer_concurrency_limit: int | None = Field(default=None, gt=0)
    admission_executor_workers: int | None = Field(default=None, gt=0)
    admission_max_outstanding: int | None = Field(default=None, gt=0)
    shutdown_drain_timeout_seconds: float | None = Field(default=None, ge=0)
    callback_url: str | None = None
    callback_token: SecretStr | None = Field(default=None, repr=False)

    @field_validator("manager_dispatch_token")
    @classmethod
    def require_canonical_dispatch_token(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        """Validate canonical encoding; entropy is a provisioning responsibility."""
        if value is None:
            # An unprovisioned development app remains fail-closed at the route.
            return None
        token = value.get_secret_value()
        if not _is_canonical_service_token(token):
            raise ValueError("manager dispatch token must be canonical 32-byte base64url")
        return value

    @field_validator("callback_token")
    @classmethod
    def require_canonical_callback_token(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        """Validate encoding only; token entropy is a provisioner responsibility."""
        if value is not None and not _is_canonical_service_token(value.get_secret_value()):
            raise ValueError("callback token must be canonical 32-byte base64url")
        return value

    @field_validator("dispatch_max_body_bytes", mode="before")
    @classmethod
    def reject_non_integer_body_limit(cls, value: object) -> object:
        if type(value) in (bool, float):
            raise ValueError("dispatch body limit must be an integer")
        return value

    @field_validator(
        "attempt_cache_max_entries", "producer_concurrency_limit",
        "admission_executor_workers", "admission_max_outstanding", mode="before"
    )
    @classmethod
    def reject_non_integer_cache_limits(cls, value: object) -> object:
        if type(value) in (bool, float):
            raise ValueError("count limits must be integers")
        return value

    @field_validator("attempt_cache_ttl_seconds", "shutdown_drain_timeout_seconds", mode="before")
    @classmethod
    def reject_boolean_durations(cls, value: object) -> object:
        if type(value) is bool:
            raise ValueError("cache durations must be numeric durations, not booleans")
        return value

    @field_validator("attempt_cache_ttl_seconds", "shutdown_drain_timeout_seconds")
    @classmethod
    def require_finite_cache_durations(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("cache durations must be finite")
        return value
