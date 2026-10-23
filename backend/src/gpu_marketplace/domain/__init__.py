"""Importing this package registers every Phase 1B mapping on ``Base.metadata``."""

from gpu_marketplace.domain.audit import AuditEvent
from gpu_marketplace.domain.base import Base
from gpu_marketplace.domain.identity import (
    Role,
    User,
    UserRole,
    Worker,
    WorkerPublicKey,
    WorkerReputationAggregate,
)
from gpu_marketplace.domain.jobs import Job, SimulationReference
from gpu_marketplace.domain.listings import GpuListing

__all__ = [
    "AuditEvent",
    "Base",
    "GpuListing",
    "Job",
    "Role",
    "SimulationReference",
    "User",
    "UserRole",
    "Worker",
    "WorkerPublicKey",
    "WorkerReputationAggregate",
]
