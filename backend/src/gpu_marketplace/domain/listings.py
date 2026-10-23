import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from gpu_marketplace.domain.base import Base
from gpu_marketplace.domain.columns import NEW_UUID, NOW, TIMESTAMPTZ, UUID_PK


class GpuListing(Base):
    __tablename__ = "gpu_listings"
    __table_args__ = (
        UniqueConstraint("id", "worker_id", name="uq_gpu_listings_id_worker_id"),
        CheckConstraint("btrim(gpu_model) <> ''", name="ck_gpu_listings_gpu_model_nonblank"),
        CheckConstraint("vram_gb > 0", name="ck_gpu_listings_vram_positive"),
        CheckConstraint("total_gpu_count > 0", name="ck_gpu_listings_total_positive"),
        CheckConstraint(
            "allocated_gpu_count >= 0 AND allocated_gpu_count <= total_gpu_count",
            name="ck_gpu_listings_allocated_range",
        ),
        CheckConstraint("status IN ('ACTIVE','PAUSED')", name="ck_gpu_listings_status"),
        CheckConstraint(
            "mock_price_per_hour IS NULL OR mock_price_per_hour >= 0",
            name="ck_gpu_listings_price_nonnegative",
        ),
        Index("ix_gpu_listings_worker_id_status", "worker_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID_PK, ForeignKey("workers.id", name="fk_gpu_listings_worker_id", ondelete="RESTRICT")
    )
    gpu_model: Mapped[str] = mapped_column(String(160))
    vram_gb: Mapped[int] = mapped_column(Integer)
    total_gpu_count: Mapped[int] = mapped_column(Integer)
    allocated_gpu_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(8), server_default=text("'ACTIVE'"))
    mock_price_per_hour: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
