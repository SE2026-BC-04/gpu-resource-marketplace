"""In-memory Listing scan policy for Phase 2D §7.2.

Candidate IDs are hints. This policy only orders inspections. The allocation
transaction rechecks each Listing independently under its own locks.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ListingScanBatch:
    listing_ids: tuple[UUID, ...]
    starting_cursor: UUID | None

    def cursor_after(self, inspected_count: int) -> UUID | None:
        """Advance over the inspected prefix, including blocked inspections."""
        if type(inspected_count) is not int or not 0 <= inspected_count <= len(self.listing_ids):
            raise ValueError("inspected_count must be within the planned batch")
        if inspected_count == 0:
            return self.starting_cursor
        return self.listing_ids[inspected_count - 1]


def plan_listing_scan(
    ordered_ids: Sequence[UUID],
    *,
    cursor: UUID | None,
    max_listings: int,
) -> ListingScanBatch:
    """Select a bounded batch from an ascending, unique UUID snapshot.

    The snapshot is already in memory and sorted by the caller. Use this as
    a policy oracle, without materializing the production candidate table.
    A missing cursor ID is still a valid position in the order. A new process
    starts with cursor=None. A refreshed snapshot can change between scans,
    so the policy makes no wait-time guarantee under continuous writes.
    """
    if type(max_listings) is not int or max_listings < 1:
        raise ValueError("max_listings must be a positive integer")

    size = len(ordered_ids)
    start = 0 if cursor is None else bisect_right(ordered_ids, cursor)
    count = min(max_listings, size)
    batch = tuple(ordered_ids[(start + offset) % size] for offset in range(count))
    return ListingScanBatch(listing_ids=batch, starting_cursor=cursor)
