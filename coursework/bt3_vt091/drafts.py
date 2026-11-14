"""Coursework model only: one monotonic editor stream per (owner, listing)."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

FIELDS = frozenset({"gpu_model", "vram_gb", "total_gpu_count", "mock_price_per_hour"})


class InvalidDraft(ValueError):
    pass


class StaleDraft(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


@dataclass(frozen=True)
class Draft:
    revision: int
    values: tuple[tuple[str, str], ...]

    def fields(self) -> dict[str, str]:
        return dict(self.values)


class DraftStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], Draft] = {}
        self._lock = asyncio.Lock()

    async def get(self, owner: str, listing: str) -> Draft | None:
        async with self._lock:
            return self._rows.get((owner, listing))

    async def save(
        self, owner: str, listing: str, revision: int, fields: Mapping[str, str]
    ) -> Draft:
        if type(revision) is not int or revision < 1:
            raise InvalidDraft("revision must be a positive integer")
        if not isinstance(fields, Mapping) or set(fields) != FIELDS:
            raise InvalidDraft("draft must contain exactly the four Listing form fields")
        if any(not isinstance(value, str) or len(value) > 4096 for value in fields.values()):
            raise InvalidDraft("draft fields must be strings of at most 4096 characters")
        candidate = Draft(revision, tuple(sorted(fields.items())))
        async with self._lock:
            current = self._rows.get((owner, listing))
            if current is not None:
                if revision < current.revision:
                    raise StaleDraft("a newer draft is already saved")
                if revision == current.revision:
                    if candidate != current:
                        raise RevisionConflict("same revision contains different fields")
                    return current
            self._rows[(owner, listing)] = candidate
            return candidate


Transport = Callable[[int, dict[str, str]], Awaitable[Draft]]


class AutoSaver:
    """No timer/debounce: each edit schedules its own immutable snapshot."""

    def __init__(self, transport: Transport, *, initial_revision: int = 0) -> None:
        if type(initial_revision) is not int or initial_revision < 0:
            raise InvalidDraft("initial_revision must be a non-negative integer")
        self._revision = initial_revision
        self._transport = transport

    def on_change(self, fields: Mapping[str, str]) -> asyncio.Task[Draft]:
        self._revision += 1
        return asyncio.create_task(self._transport(self._revision, dict(fields)))
