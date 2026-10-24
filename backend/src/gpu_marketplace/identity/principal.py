"""Trusted principal handed by GPU-003 to other modules (Listings, Jobs).

It satisfies GPU-004 ``TrustedPrincipal`` and GPU-005 ``JobPrincipal`` structurally.
Never build it from request headers, JSON or query parameters.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Role = Literal["CLIENT", "WORKER", "ADMIN"]
ROLES = frozenset({"CLIENT", "WORKER", "ADMIN"})


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Created only after a valid JWT and a fresh ACTIVE account/role read from the database."""

    user_id: UUID
    role: Role
    status: Literal["ACTIVE"] = "ACTIVE"
