from uuid import UUID

import pytest

from gpu_marketplace.manager.listing_scan_policy import plan_listing_scan


def listing(number: int) -> UUID:
    return UUID(int=number)


def test_fresh_scan_selects_one_bounded_batch() -> None:
    candidates = tuple(map(listing, (1, 3, 5, 7, 9)))

    batch = plan_listing_scan(candidates, cursor=None, max_listings=2)

    assert batch.listing_ids == (listing(1), listing(3))
    assert batch.cursor_after(2) == listing(3)


def test_partly_inspected_batch_resumes_after_last_inspection() -> None:
    candidates = tuple(map(listing, (1, 3, 5, 7)))

    batch = plan_listing_scan(candidates, cursor=listing(1), max_listings=3)
    assert batch.cursor_after(0) == listing(1)
    assert batch.cursor_after(1) == listing(3)

    resumed = plan_listing_scan(candidates, cursor=batch.cursor_after(1), max_listings=2)
    assert resumed.listing_ids == (listing(5), listing(7))


def test_wrap_uses_remaining_budget_without_repeating_an_id() -> None:
    candidates = tuple(map(listing, (1, 3, 5)))

    batch = plan_listing_scan(candidates, cursor=listing(3), max_listings=8)

    assert batch.listing_ids == (listing(5), listing(1), listing(3))
    assert batch.cursor_after(3) == listing(3)


def test_wrap_respects_actual_progress_when_batch_stops_at_the_tail() -> None:
    candidates = tuple(map(listing, (1, 3, 5, 7)))
    batch = plan_listing_scan(candidates, cursor=listing(5), max_listings=3)
    assert batch.listing_ids == (listing(7), listing(1), listing(3))

    resumed = plan_listing_scan(candidates, cursor=batch.cursor_after(1), max_listings=2)
    assert resumed.listing_ids == (listing(1), listing(3))


def test_refresh_handles_insertions_on_both_sides_of_a_deleted_cursor() -> None:
    previous = tuple(map(listing, (1, 4, 7)))
    cursor = plan_listing_scan(previous, cursor=None, max_listings=2).cursor_after(2)
    refreshed = tuple(map(listing, (1, 2, 5, 7)))

    next_batch = plan_listing_scan(refreshed, cursor=cursor, max_listings=2)
    after_wrap = plan_listing_scan(refreshed, cursor=next_batch.cursor_after(2), max_listings=2)

    assert next_batch.listing_ids == (listing(5), listing(7))
    assert after_wrap.listing_ids == (listing(1), listing(2))


def test_blocked_listings_do_not_hold_cursor_or_prevent_other_inspections() -> None:
    candidates = tuple(map(listing, range(1, 7)))
    outcomes = dict(zip(candidates, (
        "LOCK_BUSY", "HEAD_DOES_NOT_FIT", "LISTING_NOT_ACTIVE",
        "SIGNER_NOT_READY", "NO_QUEUED_HEAD", "ELIGIBLE",
    ), strict=True))
    cursor = None
    observed = []
    for _ in range(4):
        batch = plan_listing_scan(candidates, cursor=cursor, max_listings=2)
        observed.extend(outcomes[candidate] for candidate in batch.listing_ids)
        cursor = batch.cursor_after(len(batch.listing_ids))

    assert observed == [*outcomes.values(), "LOCK_BUSY", "HEAD_DOES_NOT_FIT"]


@pytest.mark.parametrize("size", range(1, 9))
@pytest.mark.parametrize("budget", (1, 2, 3, 5, 9))
def test_stable_snapshot_rotates_through_every_listing(size: int, budget: int) -> None:
    candidates = tuple(map(listing, range(1, size + 1)))
    cursor = candidates[-1]
    observed = []
    for _ in range(size + 1):
        batch = plan_listing_scan(candidates, cursor=cursor, max_listings=budget)
        assert len(batch.listing_ids) == min(size, budget)
        assert len(set(batch.listing_ids)) == len(batch.listing_ids)
        observed.extend(batch.listing_ids)
        cursor = batch.cursor_after(len(batch.listing_ids))

    assert observed == [candidates[index % size] for index in range(len(observed))]


def test_restart_begins_a_new_pass_from_current_candidates() -> None:
    candidates = tuple(map(listing, (1, 3, 5)))
    batch = plan_listing_scan(candidates, cursor=listing(3), max_listings=1)
    assert batch.listing_ids == (listing(5),)

    refreshed = tuple(map(listing, (2, 3, 5)))
    restarted = plan_listing_scan(refreshed, cursor=None, max_listings=1)
    assert restarted.listing_ids == (listing(2),)


def test_empty_snapshot_preserves_last_inspected_cursor() -> None:
    batch = plan_listing_scan((), cursor=listing(9), max_listings=1)

    assert batch.listing_ids == ()
    assert batch.cursor_after(0) == listing(9)


@pytest.mark.parametrize("max_listings", [0, -1, True, 2.5])
def test_rejects_invalid_scan_budget(max_listings: int) -> None:
    with pytest.raises(ValueError, match="max_listings"):
        plan_listing_scan((), cursor=None, max_listings=max_listings)


@pytest.mark.parametrize("inspected_count", [-1, 2, True, 0.5])
def test_rejects_invalid_inspected_count(inspected_count: int) -> None:
    batch = plan_listing_scan((listing(1),), cursor=None, max_listings=1)

    with pytest.raises(ValueError, match="inspected_count"):
        batch.cursor_after(inspected_count)
