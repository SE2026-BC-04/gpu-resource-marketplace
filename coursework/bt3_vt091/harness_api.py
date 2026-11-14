"""ASGI adapter for tests only; never mounted in the marketplace API."""

from fastapi import FastAPI, HTTPException, Request

from drafts import DraftStore, InvalidDraft, RevisionConflict, StaleDraft


def make_app(store: DraftStore) -> FastAPI:
    app = FastAPI()

    @app.put("/harness/drafts/{owner}/{listing}")
    async def save(owner: str, listing: str, request: Request):
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(422, "invalid JSON") from exc
        if not isinstance(body, dict) or set(body) != {"revision", "fields"}:
            raise HTTPException(422, "expected revision and fields")
        try:
            draft = await store.save(owner, listing, body["revision"], body["fields"])
        except InvalidDraft as exc:
            raise HTTPException(422, str(exc)) from exc
        except (StaleDraft, RevisionConflict) as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "draft storage unavailable") from exc
        return {"revision": draft.revision, "fields": draft.fields()}

    @app.get("/harness/drafts/{owner}/{listing}")
    async def get(owner: str, listing: str):
        draft = await store.get(owner, listing)
        if draft is None:
            raise HTTPException(404, "draft not found")
        return {"revision": draft.revision, "fields": draft.fields()}

    return app
