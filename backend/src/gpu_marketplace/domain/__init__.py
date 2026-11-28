"""Importing this package registers every Phase 1B and Phase 2B R1 mapping on ``Base.metadata``."""

from gpu_marketplace.domain.audit import AuditEvent
from gpu_marketplace.domain.base import Base
from gpu_marketplace.domain.evidence import JobReputationContribution, ResultInbox, SignedResult
from gpu_marketplace.domain.execution import Allocation, ExecutionAttempt, ExecutionOutbox
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
    "Allocation",
    "AuditEvent",
    "Base",
    "ExecutionAttempt",
    "ExecutionOutbox",
    "GpuListing",
    "Job",
    "JobReputationContribution",
    "ResultInbox",
    "Role",
    "SignedResult",
    "SimulationReference",
    "User",
    "UserRole",
    "Worker",
    "WorkerPublicKey",
    "WorkerReputationAggregate",
]
