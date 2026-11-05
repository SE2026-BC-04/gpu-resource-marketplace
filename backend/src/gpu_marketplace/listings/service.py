"""Listing use cases. Real transactions/locks are provided by GPU-002."""

from uuid import UUID

from .cursors import ListingCursorCodec
from .errors import ListingError, not_found
from .models import (
    ListingChanges,
    ListingPage,
    ListingPosition,
    ListingQuery,
    ListingRecord,
    ListingScope,
    ListingStatus,
    TrustedPrincipal,
)
from .ports import ListingUnitOfWork, UnitOfWorkFactory
from .policy import normalized_changes


def require_principal(principal: TrustedPrincipal) -> None:
    user_id = getattr(principal, "user_id", None)
    if (
        not isinstance(user_id, UUID)
        or user_id.version != 4
        or getattr(principal, "status", None) != "ACTIVE"
        or getattr(principal, "role", None) not in {"CLIENT", "WORKER", "ADMIN"}
    ):
        raise ListingError(401, "UNAUTHORIZED", "Authentication required.")


def require_worker(principal: TrustedPrincipal) -> None:
    require_principal(principal)
    if principal.role != "WORKER":
        raise ListingError(403, "FORBIDDEN", "Operation is not permitted.")


class ListingService:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, cursors: ListingCursorCodec
    ) -> None:
        self._uow = unit_of_work
        self._cursors = cursors

    def browse(
        self,
        principal: TrustedPrincipal,
        *,
        scope: ListingScope = "marketplace",
        status: ListingStatus | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ListingPage:
        require_principal(principal)
        if scope not in {"marketplace", "mine", "all"} or status not in {
            None,
            "ACTIVE",
            "PAUSED",
        }:
            raise ListingError(400, "INVALID_FILTER", "Invalid Listing filter.")
        if (scope == "mine" and principal.role != "WORKER") or (
            scope == "all" and principal.role != "ADMIN"
        ):
            raise ListingError(403, "FORBIDDEN", "Scope is not permitted.")
        if scope == "marketplace" and status == "PAUSED":
            raise ListingError(
                400, "INVALID_FILTER", "Marketplace shows ACTIVE Listings only."
            )
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ListingError(422, "VALIDATION_ERROR", "Invalid page size.")
        effective_status = "ACTIVE" if scope == "marketplace" else status
        context = (
            scope,
            effective_status,
            str(principal.user_id) if scope == "mine" else None,
        )
        before = self._cursors.decode(cursor, context) if cursor is not None else None
        with self._uow() as uow:
            worker_id = None
            if scope == "mine":
                worker = uow.workers.find_by_user_id(principal.user_id)
                if worker is None:
                    return ListingPage((), None)
                worker_id = worker.id
            rows = tuple(
                uow.listings.page(
                    ListingQuery(effective_status, worker_id), before, limit + 1
                )
            )
            items = rows[:limit]
            next_cursor = None
            if len(rows) > limit:
                last = items[-1]
                next_cursor = self._cursors.encode(
                    ListingPosition(last.created_at, last.id), context
                )
            return ListingPage(items, next_cursor)

    def detail(self, principal: TrustedPrincipal, listing_id: UUID) -> ListingRecord:
        require_principal(principal)
        with self._uow() as uow:
            record = uow.listings.get(listing_id)
            if record is None:
                raise not_found()
            return record

    def create(
        self, principal: TrustedPrincipal, values: ListingChanges
    ) -> ListingRecord:
        require_worker(principal)
        values = normalized_changes(values, create=True)
        with self._uow() as uow:
            worker = uow.workers.find_by_user_id(principal.user_id)
            if worker is None:
                raise ListingError(
                    409, "WORKER_PROFILE_MISSING", "Worker profile is unavailable."
                )
            record = uow.listings.create(worker.id, values)
            uow.commit()
            return record

    @staticmethod
    def _owned_locked(
        uow: ListingUnitOfWork, principal: TrustedPrincipal, listing_id: UUID
    ) -> ListingRecord:
        record = uow.listings.get_for_update(listing_id)
        # Resolve ownership from fresh DB data after the Listing lock as well.
        worker = uow.workers.find_by_user_id(principal.user_id)
        if record is None or worker is None or record.worker.id != worker.id:
            raise not_found()
        return record

    def patch(
        self, principal: TrustedPrincipal, listing_id: UUID, changes: ListingChanges
    ) -> ListingRecord:
        require_worker(principal)
        changes = normalized_changes(changes)
        with self._uow() as uow:
            record = self._owned_locked(uow, principal, listing_id)
            hardware_change = any(
                field in changes and changes[field] != getattr(record, field)
                for field in ("gpu_model", "vram_gb")
            )
            if hardware_change and uow.jobs.has_nonterminal_jobs(listing_id):
                raise ListingError(
                    409,
                    "LISTING_HARDWARE_LOCKED",
                    "Hardware cannot change while Jobs are pending or running.",
                )
            total = changes.get("total_gpu_count", record.total_gpu_count)
            if total < record.total_gpu_count:
                if total < record.allocated_gpu_count:
                    raise ListingError(
                        409,
                        "LISTING_CAPACITY_BELOW_ALLOCATED",
                        "Capacity is below allocated GPUs.",
                    )
                if total < uow.jobs.max_queued_gpu_count(listing_id):
                    raise ListingError(
                        409,
                        "LISTING_CAPACITY_BELOW_QUEUED_MAX",
                        "Capacity is below a queued Job requirement.",
                    )
            effective = {
                field: value
                for field, value in changes.items()
                if value != getattr(record, field)
            }
            result = uow.listings.update(listing_id, effective) if effective else record
            uow.commit()
            return result

    def set_status(
        self, principal: TrustedPrincipal, listing_id: UUID, status: ListingStatus
    ) -> ListingRecord:
        require_worker(principal)
        if status not in {"ACTIVE", "PAUSED"}:
            raise ValueError("invalid internal target state")
        with self._uow() as uow:
            record = self._owned_locked(uow, principal, listing_id)
            result = (
                uow.listings.set_status(listing_id, status)
                if record.status != status
                else record
            )
            uow.commit()
            return result
