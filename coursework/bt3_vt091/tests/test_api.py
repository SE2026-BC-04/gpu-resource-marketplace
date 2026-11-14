import asyncio

import httpx
import pytest

from drafts import DraftStore
from harness_api import make_app


def payload(revision=1, model="RTX 4090"):
    return {"revision": revision, "fields": {"gpu_model": model, "vram_gb": "24", "total_gpu_count": "2", "mock_price_per_hour": ""}}


def test_vt13_api_stale_and_equal_conflicts_leave_latest_readable():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(DraftStore())), base_url="http://harness") as client:
            path = "/harness/drafts/worker-a/new"
            assert (await client.get(path)).status_code == 404
            assert (await client.put(path, json=payload(2, "NEW"))).status_code == 200
            assert (await client.put(path, json=payload(1, "OLD"))).status_code == 409
            assert (await client.put(path, json=payload(2, "DIFFERENT"))).status_code == 409
            retry = await client.put(path, json=payload(2, "NEW"))
            assert retry.status_code == 200
            assert (await client.get(path)).json() == payload(2, "NEW")
    asyncio.run(scenario())


@pytest.mark.parametrize("body", ["{", "[]", "{}", '{"revision":true,"fields":{}}', '{"revision":1,"fields":{},"extra":1}'])
def test_vt14_api_rejects_invalid_input_without_creating_draft(body):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(DraftStore())), base_url="http://harness") as client:
            path = "/harness/drafts/a/x"
            assert (await client.put(path, content=body, headers={"content-type": "application/json"})).status_code == 422
            assert (await client.get(path)).status_code == 404
    asyncio.run(scenario())


def test_vt15_api_storage_failure_is_sanitized_and_preserves_previous():
    class UnavailableStore(DraftStore):
        async def save(self, owner, listing, revision, fields):
            if revision == 2:
                raise OSError("secret internal path must not be returned")
            return await super().save(owner, listing, revision, fields)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(UnavailableStore())), base_url="http://harness") as client:
            path = "/harness/drafts/a/x"
            assert (await client.put(path, json=payload(1))).status_code == 200
            failed = await client.put(path, json=payload(2))
            assert failed.status_code == 503
            assert "secret" not in failed.text
            assert (await client.get(path)).json() == payload(1)
    asyncio.run(scenario())


def test_vt16_api_two_overlapping_requests_arrive_inverted():
    class DelayedStore(DraftStore):
        def __init__(self):
            super().__init__()
            self.started, self.release = asyncio.Event(), asyncio.Event()
        async def save(self, owner, listing, revision, fields):
            if revision == 1:
                self.started.set()
                await self.release.wait()
            return await super().save(owner, listing, revision, fields)
    async def scenario():
        store = DelayedStore()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(store)), base_url="http://harness") as client:
            path = "/harness/drafts/a/x"
            old = asyncio.create_task(client.put(path, json=payload(1, "OLD")))
            await asyncio.wait_for(store.started.wait(), 5)
            try:
                assert (await client.put(path, json=payload(2, "NEW"))).status_code == 200
            finally:
                store.release.set()
            assert (await asyncio.wait_for(old, 5)).status_code == 409
            assert (await client.get(path)).json() == payload(2, "NEW")
    asyncio.run(scenario())
