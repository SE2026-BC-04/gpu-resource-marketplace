from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from gpu_marketplace.api.app import create_app
from gpu_marketplace.common.config import Settings

JWT_SECRET = "api-jobs-mount-jwt-secret-at-least-32-bytes"
LISTING_CURSOR_SECRET = "api-jobs-mount-listing-cursor-secret-32-bytes"
JOBS_CURSOR_SECRET = "api-jobs-mount-jobs-cursor-secret-32-bytes"
PREFIX = "/api/v1/jobs"


def test_create_app_mounts_jobs_submit_read_and_cancel_with_shared_principal() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            jwt_secret=JWT_SECRET,
            listing_cursor_secret=LISTING_CURSOR_SECRET,
            jobs_cursor_secret=JOBS_CURSOR_SECRET,
        ),
        database_probe=lambda: True,
        auth_schema_probe=lambda: True,
    )
    jobs_routes = []
    for mounted_route in app.routes:
        if isinstance(mounted_route, APIRoute) and mounted_route.path.startswith(PREFIX):
            jobs_routes.append(mounted_route)
            continue
        included_router = getattr(mounted_route, "original_router", None)
        jobs_routes.extend(
            route
            for route in getattr(included_router, "routes", ())
            if isinstance(route, APIRoute) and route.path.startswith(PREFIX)
        )

    assert {
        (route.path, method)
        for route in jobs_routes
        for method in route.methods or set()
    } == {
        (PREFIX, "POST"),
        (PREFIX, "GET"),
        (f"{PREFIX}/{{job_id}}", "GET"),
        (f"{PREFIX}/{{job_id}}/cancel", "POST"),
    }
    assert jobs_routes
    assert all(
        any(
            dependency.call is app.state.require_authenticated_principal
            for dependency in route.dependant.dependencies
        )
        for route in jobs_routes
    )

    with TestClient(app) as client:
        for method, path in (
            ("GET", PREFIX),
            ("POST", PREFIX),
            ("POST", f"{PREFIX}/33333333-3333-4333-8333-333333333333/cancel"),
        ):
            response = client.request(method, path)
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"
            assert response.headers["Cache-Control"] == "no-store"
