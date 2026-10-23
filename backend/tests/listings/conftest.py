from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from gpu_marketplace.listings.cursors import ListingCursorCodec
from gpu_marketplace.listings.router import create_listing_router
from gpu_marketplace.listings.service import ListingService

from .fakes import Store


@pytest.fixture
def env():
    store = Store()
    service = ListingService(
        store.open, ListingCursorCodec(b"test-only-cursor-key-not-a-secret")
    )

    def trusted_test_principal():
        # Server-side fixture injection, never a request-header authentication bypass.
        if store.actor is None:
            raise HTTPException(401)
        return store.actor

    app = FastAPI()
    app.include_router(
        create_listing_router(
            service=service, principal_dependency=trusted_test_principal
        )
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(
            store=store,
            service=service,
            client=client,
            app=app,
            principal_dependency=trusted_test_principal,
        )
