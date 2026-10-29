"""R1 PostgreSQL adapters for GPU-004's ACKed consumption ports.

Record/error constructors are supplied by the consumer: this module does not
import the unmerged Listings application or define alternate production DTOs.
Effective metadata/status writes require the approved D7 trigger. The same
UPDATE statement checks the catalog while holding its target-table write lock,
so a missing/disabled trigger fails closed without mutating a Listing.
"""

import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from types import TracebackType
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import func, insert, select, text, tuple_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from gpu_marketplace.domain.identity import Worker, WorkerReputationAggregate
from gpu_marketplace.domain.jobs import Job
from gpu_marketplace.domain.listings import GpuListing

W = TypeVar("W")
L = TypeVar("L")
logger = logging.getLogger(__name__)
METADATA_FIELDS = frozenset(
    {"gpu_model", "vram_gb", "total_gpu_count", "mock_price_per_hour"}
)
# Keep the gate in the UPDATE itself: target-table RowExclusiveLock is acquired
# before execution, preventing concurrent trigger DDL between check and write.
D7_READY = text("""
    EXISTS (
        SELECT 1 FROM pg_catalog.pg_trigger AS t
        JOIN pg_catalog.pg_proc AS p ON p.oid = t.tgfoid
        JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
        WHERE t.tgrelid = 'public.gpu_listings'::pg_catalog.regclass
          AND t.tgname = 'trg_gpu_listings_guard_update'
          AND NOT t.tgisinternal AND t.tgenabled IN ('O', 'A')
          AND t.tgtype = 19 AND t.tgqual IS NULL
          AND t.tgattr = ''::pg_catalog.int2vector
          AND n.nspname = 'public' AND p.proname = 'fn_gpu_listings_guard_update'
          AND p.pronargs = 0 AND NOT p.prosecdef
          AND p.prorettype = 'pg_catalog.trigger'::pg_catalog.regtype
          AND 'search_path=pg_catalog' = ANY(p.proconfig)
          AND pg_catalog.current_setting('session_replication_role') = 'origin'
    )
""")


class PostgresListingUnitOfWork(Generic[W, L]):
    """One fresh, restricted-role READ COMMITTED Session per single-use UoW.

    Bind worker_record=WorkerProfile, listing_record=ListingRecord and
    unavailable_error=ListingDependencyUnavailable from the existing consumer.
    The session factory must connect with gpm_api_app (not an owner DSN).
    """

    def __init__(
        self,
        sessions: Callable[[], Session],
        *,
        worker_record: Callable[..., W],
        listing_record: Callable[..., L],
        unavailable_error: Callable[[], Exception],
    ) -> None:
        self._sessions = sessions
        self._worker_record = worker_record
        self._listing_record = listing_record
        self._unavailable_error = unavailable_error
        self._session: Session | None = None
        self._entered = False
        self._committed = False
        self._failed = False
        self._locked: set[UUID] = set()
        self.workers = PostgresWorkerReader(self)
        self.listings = PostgresListingRepository(self)
        self.jobs = PostgresJobConstraintReader(self)

    def __enter__(self) -> "PostgresListingUnitOfWork[W, L]":
        if self._entered:
            raise RuntimeError("Listing UoW is single-use")
        self._entered = True
        try:
            self._session = self._sessions()
            self._session.autoflush = False
            self._session.connection(
                execution_options={"isolation_level": "READ COMMITTED"}
            )
            role, isolation = self._execute(
                text("SELECT current_user, current_setting('transaction_isolation')")
            ).one()
            if (
                role not in {"gpm_api_app", "gpm_api_rw"}
                or isolation != "read committed"
            ):
                self._fail()
            return self
        except SQLAlchemyError as error:
            self.__exit__(*sys.exc_info())
            self._fail(error)
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def _active(self) -> Session:
        if self._session is None or self._committed:
            raise RuntimeError("Listing UoW is not active")
        if self._failed:
            raise self._unavailable_error() from None
        return self._session

    def _fail(self, error: SQLAlchemyError | None = None) -> None:
        self._failed = True
        if error is not None:
            logger.error(
                "listing_store_unavailable", extra={"error_type": type(error).__name__}
            )
        raise self._unavailable_error() from None

    def _execute(self, statement: Any) -> Any:
        try:
            return self._active().execute(statement)
        except SQLAlchemyError as error:
            self._fail(error)

    def _require_lock(self, listing_id: UUID) -> None:
        self._active()
        if listing_id not in self._locked:
            raise RuntimeError(
                "Listing lock is required before constraint reads or writes"
            )

    def commit(self) -> None:
        session = self._active()
        try:
            session.commit()
        except SQLAlchemyError as error:
            self._fail(error)
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        cleanup_failed = False
        try:
            if not self._committed:
                session.rollback()
        except SQLAlchemyError:
            cleanup_failed = True
        finally:
            try:
                session.close()
            except SQLAlchemyError:
                cleanup_failed = True
            self._locked.clear()
        if cleanup_failed and exc_type is None:
            self._fail()


class PostgresWorkerReader(Generic[W, L]):
    def __init__(self, uow: PostgresListingUnitOfWork[W, L]) -> None:
        self._uow = uow

    def find_by_user_id(self, user_id: UUID) -> W | None:
        row = self._uow._execute(
            select(Worker.id, Worker.display_name).where(Worker.user_id == user_id)
        ).one_or_none()
        return (
            None
            if row is None
            else self._uow._worker_record(id=row.id, display_name=row.display_name)
        )


class PostgresListingRepository(Generic[W, L]):
    def __init__(self, uow: PostgresListingUnitOfWork[W, L]) -> None:
        self._uow = uow

    @staticmethod
    def _select() -> Any:
        # Public-safe columns only; no ORM identity-map or lazy loading.
        return (
            select(
                GpuListing.id,
                GpuListing.worker_id,
                Worker.display_name,
                GpuListing.gpu_model,
                GpuListing.vram_gb,
                GpuListing.total_gpu_count,
                GpuListing.allocated_gpu_count,
                GpuListing.status,
                GpuListing.mock_price_per_hour,
                GpuListing.created_at,
                GpuListing.updated_at,
                func.coalesce(WorkerReputationAggregate.successful_jobs, 0).label(
                    "successful_jobs"
                ),
                func.coalesce(WorkerReputationAggregate.worker_fault_jobs, 0).label(
                    "worker_fault_jobs"
                ),
            )
            .select_from(GpuListing)
            .join(Worker, Worker.id == GpuListing.worker_id)
            .outerjoin(
                WorkerReputationAggregate,
                WorkerReputationAggregate.worker_id == Worker.id,
            )
        )

    def _record(self, row: Any) -> L:
        values = dict(row._mapping)
        worker_id = values.pop("worker_id")
        display_name = values.pop("display_name")
        return self._uow._listing_record(
            **values,
            worker=self._uow._worker_record(id=worker_id, display_name=display_name),
        )

    def page(self, query: Any, before: Any, limit: int) -> Sequence[L]:
        if type(limit) is not int or not 1 <= limit <= 101:
            raise ValueError("Invalid internal page size")
        if query.status not in {None, "ACTIVE", "PAUSED"}:
            raise ValueError("Invalid internal status filter")
        statement = self._select()
        if query.status is not None:
            statement = statement.where(GpuListing.status == query.status)
        if query.worker_id is not None:
            statement = statement.where(GpuListing.worker_id == query.worker_id)
        if before is not None:
            statement = statement.where(
                tuple_(GpuListing.created_at, GpuListing.id)
                < tuple_(before.created_at, before.id)
            )
        rows = self._uow._execute(
            statement.order_by(
                GpuListing.created_at.desc(), GpuListing.id.desc()
            ).limit(limit)
        ).all()
        return tuple(self._record(row) for row in rows)

    def get(self, listing_id: UUID) -> L | None:
        row = self._uow._execute(
            self._select().where(GpuListing.id == listing_id)
        ).one_or_none()
        return None if row is None else self._record(row)

    def get_for_update(self, listing_id: UUID) -> L | None:
        found = self._uow._execute(
            select(GpuListing.id)
            .where(GpuListing.id == listing_id)
            .with_for_update(of=GpuListing)
        ).scalar_one_or_none()
        if found is None:
            return None
        self._uow._locked.add(listing_id)
        # A separate READ COMMITTED statement after lock acquisition sees the
        # fresh committed Listing/Worker/reputation state, even after waiting.
        return self.get(listing_id)

    def create(self, worker_id: UUID, values: Mapping[str, Any]) -> L:
        if set(values) - METADATA_FIELDS or not {
            "gpu_model",
            "vram_gb",
            "total_gpu_count",
        } <= set(values):
            raise ValueError("Invalid internal create fields")
        listing_id = self._uow._execute(
            insert(GpuListing)
            .values(worker_id=worker_id, **values)
            .returning(GpuListing.id)
        ).scalar_one()
        record = self.get(listing_id)
        if record is None:
            self._uow._fail()
        return record

    def update(self, listing_id: UUID, changes: Mapping[str, Any]) -> L:
        self._uow._require_lock(listing_id)
        if set(changes) - METADATA_FIELDS:
            raise ValueError("Invalid internal update fields")
        record = self.get(listing_id)
        if record is None:
            self._uow._fail()
        effective = {
            key: value
            for key, value in changes.items()
            if value != getattr(record, key)
        }
        if not effective:
            return record
        return self._write(listing_id, effective)

    def set_status(self, listing_id: UUID, status: str) -> L:
        self._uow._require_lock(listing_id)
        if status not in {"ACTIVE", "PAUSED"}:
            raise ValueError("Invalid internal status")
        record = self.get(listing_id)
        if record is None:
            self._uow._fail()
        if record.status == status:
            return record
        return self._write(listing_id, {"status": status})

    def _write(self, listing_id: UUID, changes: Mapping[str, Any]) -> L:
        # Column allowlists are validated by update/set_status. Never send the
        # complete ORM row, allocation/owner or a caller-computed timestamp.
        changed_id = self._uow._execute(
            update(GpuListing.__table__)
            .where(GpuListing.id == listing_id, D7_READY)
            .values(**changes)
            .returning(GpuListing.id)
        ).scalar_one_or_none()
        if changed_id is None:
            self._uow._fail()
        record = self.get(changed_id)
        if record is None:
            self._uow._fail()
        return record


class PostgresJobConstraintReader(Generic[W, L]):
    def __init__(self, uow: PostgresListingUnitOfWork[W, L]) -> None:
        self._uow = uow

    def has_nonterminal_jobs(self, listing_id: UUID) -> bool:
        self._uow._require_lock(listing_id)
        return self._uow._execute(
            select(
                select(Job.id)
                .where(
                    Job.listing_id == listing_id, Job.status.in_(("QUEUED", "RUNNING"))
                )
                .exists()
            )
        ).scalar_one()

    def max_queued_gpu_count(self, listing_id: UUID) -> int:
        self._uow._require_lock(listing_id)
        return self._uow._execute(
            select(func.coalesce(func.max(Job.requested_gpu_count), 0)).where(
                Job.listing_id == listing_id, Job.status == "QUEUED"
            )
        ).scalar_one()
