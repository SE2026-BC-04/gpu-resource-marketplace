import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gpu_marketplace.domain.base import Base
from gpu_marketplace.domain.columns import NEW_UUID, NOW, TIMESTAMPTZ, UUID_PK


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (CheckConstraint("code IN ('CLIENT','WORKER','ADMIN')", name="ck_roles_code"),)

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    description: Mapped[str] = mapped_column(String(100))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("login_name", name="uq_users_login_name"),
        CheckConstraint("status IN ('ACTIVE','DISABLED')", name="ck_users_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    login_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'ACTIVE'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_code", name="uq_user_roles_user_id_role_code"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID_PK,
        ForeignKey("users.id", name="fk_user_roles_user_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("roles.code", name="fk_user_roles_role_code", ondelete="RESTRICT")
    )
    assigned_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_workers_user_id"),
        CheckConstraint("role_code = 'WORKER'", name="ck_workers_role_code"),
        ForeignKeyConstraint(
            ["user_id", "role_code"],
            ["user_roles.user_id", "user_roles.role_code"],
            name="fk_workers_user_role",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    role_code: Mapped[str] = mapped_column(String(8), server_default=text("'WORKER'"))
    display_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)


class WorkerPublicKey(Base):
    __tablename__ = "worker_public_keys"
    __table_args__ = (
        UniqueConstraint("worker_id", "key_id", name="uq_worker_public_keys_worker_id_key_id"),
        CheckConstraint("octet_length(public_key_raw) = 32", name="ck_worker_public_keys_raw_len"),
        CheckConstraint(
            "retired_at IS NULL OR retired_at >= registered_at",
            name="ck_worker_public_keys_retired_after_registered",
        ),
    )

    key_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID_PK,
        ForeignKey("workers.id", name="fk_worker_public_keys_worker_id", ondelete="RESTRICT"),
    )
    public_key_raw: Mapped[bytes] = mapped_column(LargeBinary)
    registered_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    retired_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class WorkerReputationAggregate(Base):
    __tablename__ = "worker_reputation_aggregates"
    __table_args__ = (
        CheckConstraint("successful_jobs >= 0", name="ck_worker_reputation_aggregates_successful_nonneg"),
        CheckConstraint("worker_fault_jobs >= 0", name="ck_worker_reputation_aggregates_fault_nonneg"),
    )

    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID_PK,
        ForeignKey("workers.id", name="fk_worker_reputation_aggregates_worker_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    successful_jobs: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    worker_fault_jobs: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
