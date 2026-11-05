"""Listing request/response DTOs from API Contract section 7."""

from decimal import Decimal, localcontext
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    UUID4,
    field_validator,
    model_validator,
)

from .models import ListingChanges, ListingRecord, utc_timestamp

PositiveInt32 = Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]
PriceString = Annotated[str, Field(strict=True, pattern=r"^[0-9]+\.[0-9]{2}$")]


class ListingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gpu_model: StrictStr | None = None
    vram_gb: PositiveInt32 | None = None
    total_gpu_count: PositiveInt32 | None = None
    mock_price_per_hour: PriceString | None = None

    @field_validator("gpu_model")
    @classmethod
    def model_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not 1 <= len(value) <= 160:
            raise ValueError("invalid GPU model")
        return value

    @field_validator("mock_price_per_hour")
    @classmethod
    def price_range(cls, value: str | None) -> str | None:
        if value is not None and Decimal(value) > Decimal("9999999999.99"):
            raise ValueError("price out of range")
        return value

    @model_validator(mode="after")
    def patch_fields(self) -> "ListingPatch":
        if not self.model_fields_set:
            raise ValueError("empty patch")
        for field in self.model_fields_set - {"mock_price_per_hour"}:
            if getattr(self, field) is None:
                raise ValueError("required values cannot be null")
        return self

    def changes(self) -> ListingChanges:
        values = self.model_dump(exclude_unset=True)
        if (
            "mock_price_per_hour" in values
            and values["mock_price_per_hour"] is not None
        ):
            values["mock_price_per_hour"] = Decimal(values["mock_price_per_hour"])
        return values


class ListingCreate(ListingPatch):
    gpu_model: StrictStr
    vram_gb: PositiveInt32
    total_gpu_count: PositiveInt32


class ReputationDTO(BaseModel):
    successful_jobs: Annotated[int, Field(strict=True, ge=0)]
    worker_fault_jobs: Annotated[int, Field(strict=True, ge=0)]
    success_rate: str | None


class WorkerDTO(BaseModel):
    id: UUID4
    display_name: str
    reputation: ReputationDTO


class ListingDTO(BaseModel):
    id: UUID4
    worker: WorkerDTO
    gpu_model: str
    vram_gb: PositiveInt32
    total_gpu_count: PositiveInt32
    allocated_gpu_count: Annotated[int, Field(strict=True, ge=0)]
    available_gpu_count: Annotated[int, Field(strict=True, ge=0)]
    status: Literal["ACTIVE", "PAUSED"]
    accepting_jobs: bool
    mock_price_per_hour: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: ListingRecord) -> "ListingDTO":
        eligible = record.successful_jobs + record.worker_fault_jobs
        with localcontext() as context:
            context.prec = 40
            ratio = (
                format(Decimal(record.successful_jobs) / eligible, ".4f")
                if eligible
                else None
            )
        price = record.mock_price_per_hour
        if price is not None and (
            not price.is_finite()
            or price < 0
            or price > Decimal("9999999999.99")
            or price != price.quantize(Decimal("0.01"))
        ):
            raise ValueError("adapter returned invalid price")
        return cls(
            id=record.id,
            worker=WorkerDTO(
                id=record.worker.id,
                display_name=record.worker.display_name,
                reputation=ReputationDTO(
                    successful_jobs=record.successful_jobs,
                    worker_fault_jobs=record.worker_fault_jobs,
                    success_rate=ratio,
                ),
            ),
            gpu_model=record.gpu_model,
            vram_gb=record.vram_gb,
            total_gpu_count=record.total_gpu_count,
            allocated_gpu_count=record.allocated_gpu_count,
            available_gpu_count=record.total_gpu_count - record.allocated_gpu_count,
            status=record.status,
            accepting_jobs=record.status == "ACTIVE",
            mock_price_per_hour=format(price, ".2f") if price is not None else None,
            created_at=utc_timestamp(record.created_at),
            updated_at=utc_timestamp(record.updated_at),
        )


class ListingPageDTO(BaseModel):
    items: list[ListingDTO]
    next_cursor: str | None
