"""Explicit, isolated configuration validation for future Phase 2 Manager use.

This module deliberately does not read environment variables, construct a
global Settings object, connect to PostgreSQL, or activate any Manager loops.
The future composition boundary must pass Manager-owned values explicitly and
must separately verify live database identity, schema, and grants.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, field_validator
from sqlalchemy.engine import make_url


_BEARER_TOKEN68 = re.compile(r"[A-Za-z0-9._~+/-]+={0,}")
_MINIMUM_DISPATCH_TOKEN_CONTENT_CHARACTERS = 32
_MANAGER_DATABASE_LOGIN = "gpm_manager_app"
_CONFIG_FIELDS = frozenset({"dispatch_token", "database_url"})
_SAFE_VALIDATION_MESSAGES = {
    ("dispatch_token", "missing"): "dispatch_token is required",
    ("dispatch_token", "string_type"): "dispatch_token must be a string",
    ("dispatch_token", "value_error"): "dispatch_token is invalid",
    ("database_url", "missing"): "database_url is required",
    ("database_url", "string_type"): "database_url must be a string",
    ("database_url", "value_error"): "database_url is invalid",
}


class _ManagerPhase2ConfigModel(BaseModel):
    """Private validator model; raw Pydantic errors must not cross the API."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    dispatch_token: SecretStr
    database_url: SecretStr

    @field_validator("dispatch_token")
    @classmethod
    def validate_dispatch_token(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value()
        if not token or token.isspace():
            raise ValueError("Manager dispatch token must not be empty")
        if _BEARER_TOKEN68.fullmatch(token) is None:
            raise ValueError(
                "Manager dispatch token must be a valid Bearer token68 value"
            )
        non_padding_content = token.rstrip("=")
        if len(non_padding_content) < _MINIMUM_DISPATCH_TOKEN_CONTENT_CHARACTERS:
            raise ValueError(
                "Manager dispatch token must contain at least 32 non-padding characters"
            )
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        raw_url = value.get_secret_value()
        try:
            url = make_url(raw_url)
        except Exception:
            # Parser exceptions may contain the full DSN and password.
            raise ValueError("Manager database URL is invalid") from None

        if url.drivername != "postgresql+psycopg":
            raise ValueError(
                "Manager database URL must use the approved postgresql+psycopg driver"
            )
        if not url.host or not url.database:
            raise ValueError(
                "Manager database URL must include a host and database name"
            )
        if url.username != _MANAGER_DATABASE_LOGIN:
            raise ValueError(
                "Manager database URL must use the configured gpm_manager_app login"
            )
        if url.query:
            # SQLAlchemy's psycopg dialect lets URL query keys override or extend
            # the authority-derived connection arguments. No Manager connection
            # option is approved here, so reject the entire query without
            # normalizing or silently dropping any setting.
            raise ValueError(
                "Manager database URL must not include query parameters"
            )
        return value


class ManagerConfigValidationError(ValueError):
    """Redacted configuration error safe for logs and structured diagnostics."""


@dataclass(frozen=True, slots=True, init=False)
class ManagerPhase2Config:
    """Manager-owned Phase 2 inputs; all values must be supplied explicitly.

    The 32-character non-padding dispatch-token floor is only a representation
    check. It does not measure or prove entropy. Secure provisioning of at least 256
    random bits and agreement on the provisioning format remain owner/interface
    requirements. No other component's credential is accepted or retained.
    """

    dispatch_token: SecretStr = field(repr=True)
    database_url: SecretStr = field(repr=True)

    def __init__(
        self,
        *,
        dispatch_token: str | SecretStr,
        database_url: str | SecretStr,
    ) -> None:
        validated = _validate_values(
            {"dispatch_token": dispatch_token, "database_url": database_url}
        )
        object.__setattr__(self, "dispatch_token", validated.dispatch_token)
        object.__setattr__(self, "database_url", validated.database_url)

    @classmethod
    def _from_validated(
        cls,
        validated: _ManagerPhase2ConfigModel,
    ) -> ManagerPhase2Config:
        instance = object.__new__(cls)
        object.__setattr__(instance, "dispatch_token", validated.dispatch_token)
        object.__setattr__(instance, "database_url", validated.database_url)
        return instance


def _validate_values(values: Mapping[str, object]) -> _ManagerPhase2ConfigModel:
    sanitized_message: str | None = None
    try:
        return _ManagerPhase2ConfigModel.model_validate(values)
    except ValidationError as error:
        safe_issues: list[str] = []
        for issue in error.errors(
            include_input=False,
            include_context=False,
            include_url=False,
        ):
            known_field = next(
                (
                    part
                    for part in issue["loc"]
                    if isinstance(part, str) and part in _CONFIG_FIELDS
                ),
                None,
            )
            category = issue["type"]
            if category == "extra_forbidden":
                safe_issues.append("configuration contains unsupported fields")
            elif known_field is None:
                safe_issues.append("configuration is invalid")
            else:
                safe_issues.append(
                    _SAFE_VALIDATION_MESSAGES.get(
                        (known_field, category),
                        "configuration is invalid",
                    )
                )
        sanitized_message = "; ".join(safe_issues)

    # Raise outside the except block so the raw ValidationError does not remain
    # reachable through the public exception's context.
    raise ManagerConfigValidationError(
        f"Invalid Manager Phase 2 configuration: {sanitized_message}"
    )


def validate_manager_phase2_config(
    values: Mapping[str, object],
) -> ManagerPhase2Config:
    """Validate explicitly supplied Manager Phase 2 values.

    Missing required values fail closed. This is a pure configuration gate:
    it does not read environment variables, retry, assert readiness, or verify
    PostgreSQL session identity, schema revision, or column grants.
    """

    return ManagerPhase2Config._from_validated(_validate_values(values))
