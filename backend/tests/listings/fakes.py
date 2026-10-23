"""Test-only transactional double, NOT a production repository or row-lock proof."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from gpu_marketplace.listings.models import (
    ListingPosition,
    ListingQuery,
    ListingRecord,
    WorkerProfile,
)

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str
    status: str = "ACTIVE"


class Store:
    def __init__(self):
        self.w1 = Principal(uuid4(), "WORKER")
        self.w2 = Principal(uuid4(), "WORKER")
        self.client = Principal(uuid4(), "CLIENT")
        self.admin = Principal(uuid4(), "ADMIN")
        self.actor = self.w1
        self.workers = {
            self.w1.user_id: WorkerProfile(uuid4(), "Worker One"),
            self.w2.user_id: WorkerProfile(uuid4(), "Worker Two"),
        }
        self.l1 = ListingRecord(
            uuid4(),
            self.workers[self.w1.user_id],
            "A100 simulated",
            80,
            8,
            3,
            "ACTIVE",
            Decimal("12.50"),
            NOW,
            NOW,
            7,
            3,
        )
        self.l2 = ListingRecord(
            uuid4(),
            self.workers[self.w2.user_id],
            "RTX simulated",
            24,
            2,
            0,
            "PAUSED",
            None,
            NOW,
            NOW,
        )
        self.records = {self.l1.id: self.l1, self.l2.id: self.l2}
        self.job_rows = {self.l1.id: [("RUNNING", 3), ("QUEUED", 6)]}
        self.events = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = None

    def open(self):
        return FakeUow(self)


class FakeUow:
    def __init__(self, store):
        self.store = store
        self.rows = dict(store.records)
        self.locked = set()
        self.workers = Workers(store)
        self.listings = Listings(self)
        self.jobs = Jobs(self)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if not self.committed:
            self.store.rollbacks += 1

    def commit(self):
        if self.store.fail_commit:
            raise self.store.fail_commit
        self.store.records = dict(self.rows)
        self.store.commits += 1
        self.committed = True


class Workers:
    def __init__(self, store):
        self.store = store

    def find_by_user_id(self, user_id):
        return self.store.workers.get(user_id)


class Listings:
    def __init__(self, uow):
        self.uow = uow

    def page(self, query: ListingQuery, before: ListingPosition | None, limit):
        rows = [
            row
            for row in self.uow.rows.values()
            if (query.status is None or row.status == query.status)
            and (query.worker_id is None or row.worker.id == query.worker_id)
            and (
                before is None
                or (row.created_at, row.id.int) < (before.created_at, before.id.int)
            )
        ]
        return sorted(rows, key=lambda row: (row.created_at, row.id.int), reverse=True)[
            :limit
        ]

    def get(self, listing_id):
        return self.uow.rows.get(listing_id)

    def get_for_update(self, listing_id):
        self.uow.locked.add(listing_id)
        self.uow.store.events.append(("lock", listing_id))
        return self.get(listing_id)

    def create(self, worker_id, values):
        assert set(values) <= {
            "gpu_model",
            "vram_gb",
            "total_gpu_count",
            "mock_price_per_hour",
        }
        worker = next(
            worker
            for worker in self.uow.store.workers.values()
            if worker.id == worker_id
        )
        record = ListingRecord(
            uuid4(),
            worker,
            values["gpu_model"],
            values["vram_gb"],
            values["total_gpu_count"],
            0,
            "ACTIVE",
            values.get("mock_price_per_hour"),
            NOW,
            NOW,
        )
        self.uow.rows[record.id] = record
        self.uow.store.events.append(("insert", dict(values)))
        return record

    def update(self, listing_id, changes):
        assert listing_id in self.uow.locked
        assert set(changes) <= {
            "gpu_model",
            "vram_gb",
            "total_gpu_count",
            "mock_price_per_hour",
        }
        self.uow.store.events.append(("update", dict(changes)))
        result = replace(self.get(listing_id), **changes)
        self.uow.rows[listing_id] = result
        return result

    def set_status(self, listing_id, status):
        assert listing_id in self.uow.locked
        self.uow.store.events.append(("status", status))
        result = replace(self.get(listing_id), status=status)
        self.uow.rows[listing_id] = result
        return result


class Jobs:
    def __init__(self, uow):
        self.uow = uow

    def has_nonterminal_jobs(self, listing_id):
        assert listing_id in self.uow.locked
        self.uow.store.events.append(("jobs_nonterminal", listing_id))
        return any(
            state in {"QUEUED", "RUNNING"}
            for state, _ in self.uow.store.job_rows.get(listing_id, [])
        )

    def max_queued_gpu_count(self, listing_id):
        assert listing_id in self.uow.locked
        self.uow.store.events.append(("jobs_queued", listing_id))
        return max(
            (
                count
                for state, count in self.uow.store.job_rows.get(listing_id, [])
                if state == "QUEUED"
            ),
            default=0,
        )
