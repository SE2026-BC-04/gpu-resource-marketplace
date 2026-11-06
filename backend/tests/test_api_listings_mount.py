from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from gpu_marketplace.api.app import create_app
from gpu_marketplace.common.config import Settings

JWT_SECRET = "api-listings-mount-jwt-secret-at-least-32-bytes"
CURSOR_SECRET = "api-listings-mount-cursor-secret-32-bytes-minimum"
PREFIX = "/api/v1/gpu-listings"


def test_create_app_mounts_listings_on_the_shared_principal_dependency() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            jwt_secret=JWT_SECRET,
            listing_cursor_secret=CURSOR_SECRET,
        ),
        database_probe=lambda: True,
        auth_schema_probe=lambda: True,
    )
    # Recent FastAPI versions keep included routers lazy in ``app.routes``;
    # older versions flatten their APIRoutes directly. Inspect either shape.
    listing_routes = []
    for mounted_route in app.routes:
        if isinstance(mounted_route, APIRoute) and mounted_route.path.startswith(PREFIX):
            listing_routes.append(mounted_route)
            continue
        included_router = getattr(mounted_route, "original_router", None)
        listing_routes.extend(
            route
            for route in getattr(included_router, "routes", ())
            if isinstance(route, APIRoute) and route.path.startswith(PREFIX)
        )

    assert {
        (route.path, method)
        for route in listing_routes
        for method in route.methods or set()
    } == {
        (PREFIX, "GET"),
        (PREFIX, "POST"),
        (f"{PREFIX}/{{listing_id}}", "GET"),
        (f"{PREFIX}/{{listing_id}}", "PATCH"),
        (f"{PREFIX}/{{listing_id}}/pause", "POST"),
        (f"{PREFIX}/{{listing_id}}/resume", "POST"),
    }
    assert listing_routes
    assert all(
        any(
            dependency.call is app.state.require_authenticated_principal
            for dependency in route.dependant.dependencies
        )
        for route in listing_routes
    )

    with TestClient(app) as client:
        response = client.get(PREFIX)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"
