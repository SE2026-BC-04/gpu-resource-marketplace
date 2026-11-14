"""Expected outcomes come from PLAN.md ACs, not from the save implementation."""

import asyncio
import itertools

import pytest

from drafts import AutoSaver, DraftStore, InvalidDraft, RevisionConflict, StaleDraft


def fields(model="RTX 4090"):
    return {"gpu_model": model, "vram_gb": "24", "total_gpu_count": "2", "mock_price_per_hour": ""}


def test_vt01_edit_saves_automatically_and_snapshots_input():
    async def scenario():
        store = DraftStore()
        saver = AutoSaver(lambda rev, value: store.save("worker-a", "new", rev, value))
        form = fields()
        saving = saver.on_change(form)
        form["gpu_model"] = "changed after scheduling"
        await saving
        assert (await store.get("worker-a", "new")).fields() == fields()
    asyncio.run(scenario())


def test_vt02_incomplete_form_can_be_restored_and_copies_are_independent():
    async def scenario():
        store = DraftStore()
        incomplete = {key: "" for key in fields()}
        await store.save("worker-a", "new", 1, incomplete)
        read = (await store.get("worker-a", "new")).fields()
        read["gpu_model"] = "external mutation"
        assert (await store.get("worker-a", "new")).fields() == incomplete
    asyncio.run(scenario())


def test_vt03_stale_save_cannot_replace_newer():
    async def scenario():
        store = DraftStore()
        await store.save("worker-a", "new", 2, fields("NEW"))
        with pytest.raises(StaleDraft):
            await store.save("worker-a", "new", 1, fields("OLD"))
        saved = await store.get("worker-a", "new")
        assert saved.revision == 2
        assert saved.fields() == fields("NEW")
    asyncio.run(scenario())


def test_vt04_delayed_old_request_finishes_after_new_request():
    async def scenario():
        store, old_started, release_old = DraftStore(), asyncio.Event(), asyncio.Event()
        async def transport(revision, value):
            if revision == 1:
                old_started.set()
                await release_old.wait()
            return await store.save("worker-a", "new", revision, value)
        saver = AutoSaver(transport)
        old = saver.on_change(fields("OLD"))
        await asyncio.wait_for(old_started.wait(), 5)
        try:
            await saver.on_change(fields("NEW"))
        finally:
            release_old.set()
        with pytest.raises(StaleDraft):
            await asyncio.wait_for(old, 5)
        assert (await store.get("worker-a", "new")).fields() == fields("NEW")
    asyncio.run(scenario())


@pytest.mark.parametrize("order", list(itertools.permutations([1, 2, 3])))
def test_vt05_all_arrival_orders_preserve_maximum_revision(order):
    async def scenario():
        store, highest = DraftStore(), 0
        for revision in order:
            if revision < highest:
                with pytest.raises(StaleDraft):
                    await store.save("worker-a", "new", revision, fields(str(revision)))
            else:
                await store.save("worker-a", "new", revision, fields(str(revision)))
                highest = revision
            current = await store.get("worker-a", "new")
            assert (current.revision, current.fields()["gpu_model"]) == (highest, str(highest))
    asyncio.run(scenario())


def test_vt06_identical_retry_is_idempotent_but_conflicting_retry_is_rejected():
    async def scenario():
        store = DraftStore()
        original = await store.save("worker-a", "new", 1, fields("FIRST"))
        assert await store.save("worker-a", "new", 1, fields("FIRST")) == original
        with pytest.raises(RevisionConflict):
            await store.save("worker-a", "new", 1, fields("OTHER"))
        assert await store.get("worker-a", "new") == original
    asyncio.run(scenario())


@pytest.mark.parametrize("revision", [0, -1, True, "2", 1.5, None])
def test_vt07_invalid_revision_has_no_write(revision):
    async def scenario():
        store = DraftStore()
        with pytest.raises(InvalidDraft):
            await store.save("worker-a", "new", revision, fields())
        assert await store.get("worker-a", "new") is None
    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [{}, {**fields(), "jwt": "not-allowed"}, {**fields(), "vram_gb": 24}, {**fields(), "gpu_model": "x" * 4097}, None])
def test_vt08_invalid_schema_does_not_replace_previous_draft(payload):
    async def scenario():
        store = DraftStore()
        previous = await store.save("worker-a", "new", 1, fields())
        with pytest.raises(InvalidDraft):
            await store.save("worker-a", "new", 2, payload)
        assert await store.get("worker-a", "new") == previous
    asyncio.run(scenario())


def test_vt09_drafts_are_scoped_by_owner_and_listing():
    async def scenario():
        store = DraftStore()
        for owner, listing, model in [("a", "x", "AX"), ("b", "x", "BX"), ("a", "y", "AY")]:
            await store.save(owner, listing, 1, fields(model))
        assert (await store.get("a", "x")).fields() == fields("AX")
        assert (await store.get("b", "x")).fields() == fields("BX")
        assert (await store.get("a", "y")).fields() == fields("AY")
        assert await store.get("unknown", "x") is None
    asyncio.run(scenario())


def test_vt10_storage_failure_keeps_previous_draft_and_next_edit_recovers():
    async def scenario():
        store = DraftStore()
        await store.save("a", "x", 1, fields("SAFE"))
        async def transport(revision, value):
            if revision == 2:
                raise OSError("injected unavailable storage")
            return await store.save("a", "x", revision, value)
        saver = AutoSaver(transport, initial_revision=1)
        with pytest.raises(OSError):
            await saver.on_change(fields("FAILED"))
        assert (await store.get("a", "x")).fields() == fields("SAFE")
        await saver.on_change(fields("RECOVERED"))
        assert (await store.get("a", "x")).fields() == fields("RECOVERED")
    asyncio.run(scenario())


def test_vt11_resume_uses_saved_revision_instead_of_resetting_to_one():
    async def scenario():
        store = DraftStore()
        current = await store.save("a", "x", 10, fields("SAVED"))
        saver = AutoSaver(lambda rev, value: store.save("a", "x", rev, value), initial_revision=current.revision)
        assert (await saver.on_change(fields("RESUMED"))).revision == 11
    asyncio.run(scenario())


@pytest.mark.parametrize("revision", [-1, True])
def test_vt12_invalid_initial_revision_is_rejected(revision):
    with pytest.raises(InvalidDraft):
        AutoSaver(lambda rev, value: None, initial_revision=revision)
