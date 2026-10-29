"""Pure validation for use cases, including callers outside HTTP."""

from decimal import Decimal
from typing import cast

from .errors import ListingError, invalid_fields
from .models import ListingChanges

MUTABLE_FIELDS = frozenset(
    {"gpu_model", "vram_gb", "total_gpu_count", "mock_price_per_hour"}
)


def normalized_changes(
    values: ListingChanges, *, create: bool = False
) -> ListingChanges:
    if set(values) - MUTABLE_FIELDS:
        raise ListingError(
            400, "UNKNOWN_FIELD", "Request contains an unsupported field."
        )
    if not values or (
        create and not {"gpu_model", "vram_gb", "total_gpu_count"} <= set(values)
    ):
        raise invalid_fields()
    result = dict(values)
    if "gpu_model" in result:
        model = result["gpu_model"]
        if not isinstance(model, str) or not 1 <= len(model.strip()) <= 160:
            raise invalid_fields()
        result["gpu_model"] = model.strip()
    for field in ("vram_gb", "total_gpu_count"):
        if field in result and (
            type(result[field]) is not int or not 1 <= result[field] <= 2**31 - 1
        ):
            raise invalid_fields()
    price = result.get("mock_price_per_hour")
    if price is not None:
        if not isinstance(price, Decimal) or not price.is_finite():
            raise invalid_fields()
        if not 0 <= price <= Decimal("9999999999.99") or price != price.quantize(
            Decimal("0.01")
        ):
            raise invalid_fields()
    return cast(ListingChanges, result)
