"""Explicit, isolated configuration validation for future Phase 2 Manager use.

This module deliberately does not read environment variables, construct a
global Settings object, connect to PostgreSQL, or activate any Manager loops.
The future composition boundary must pass Manager-owned values explicitly and
must separately verify live database identity, schema, and grants.
"""

from collections.abc import Mapping
import re

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from sqlalchemy.engine import make_url


_BEARER_TOKEN68 = re.compile(r"[A-Za-z0-9._~+/-]+={0,}")
_MINIMUM_DISPATCH_TOKEN_CHARACTERS = 32
_MANAGER_DATABASE_LOGIN = "gpm_manager_app"


class ManagerPhase2Config(BaseModel):
    """Manager-owned Phase 2 inputs; all values must be supplied explicitly.

    The 32-character dispatch-token floor is only a representation check. It
    does not measure or prove entropy. Secure provisioning of at least 256
    random bits and agreement on the provisioning format remain owner/interface
    requirements. No other component's credential is accepted or retained.
    """

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
        if len(token) < _MINIMUM_DISPATCH_TOKEN_CHARACTERS:
            raise ValueError(
                "Manager dispatch token must contain at least 32 characters"
            )
        if _BEARER_TOKEN68.fullmatch(token) is None:
            raise ValueError(
                "Manager dispatch token must be a valid Bearer token68 value"
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
        return value


def validate_manager_phase2_config(
    values: Mapping[str, object],
) -> ManagerPhase2Config:
    """Validate explicitly supplied Manager Phase 2 values.

    Missing required values fail closed. This is a pure configuration gate:
    it does not read environment variables, retry, assert readiness, or verify
    PostgreSQL session identity, schema revision, or column grants.
    """

    return ManagerPhase2Config.model_validate(values)
