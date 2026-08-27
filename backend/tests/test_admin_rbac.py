"""Regression guard for the M11 defect.

`_require_admin` was applied per endpoint and had been forgotten on seven read
handlers, so any authenticated viewer could read the scoring weights, source
portal configuration, job schedule, job error history and the dead-letter queue.

The check now lives on the router. These tests are parametrised from the
router's own route table rather than a hand-written list, so an endpoint added
later is covered without anyone remembering to add it here.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import require_admin
from app.api.admin import router as admin_router
from app.api.auth import get_current_user

ADMIN_ROUTES = [
    (method, route.path)
    for route in admin_router.routes
    for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"})
]

# Placeholders for path parameters; the role check runs before any handler body.
PATH_PARAMS = {"{user_id}": "some-user-id", "{job_name}": "check_awards", "{call_id}": "some-call-id"}


def _concrete(path: str) -> str:
    for placeholder, value in PATH_PARAMS.items():
        path = path.replace(placeholder, value)
    return path


@pytest.fixture
def client_as():
    """Build a client whose authenticated user has the given role."""

    def _build(role: str):
        app = FastAPI()
        app.include_router(admin_router, prefix="/api/admin")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "u1", "role": role, "name": "Test User",
        }
        return TestClient(app)

    return _build


def test_the_route_table_is_not_empty():
    """If this breaks, the parametrisation below is silently testing nothing."""
    assert len(ADMIN_ROUTES) >= 15


class TestNonAdminIsRefused:
    @pytest.mark.parametrize("role", ["operator", "viewer", "manager", ""])
    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_every_admin_route_refuses_a_non_admin(self, client_as, role, method, path):
        response = client_as(role).request(method, _concrete(f"/api/admin{path}"), json={})
        assert response.status_code == 403, (
            f"{method} {path} returned {response.status_code} for role {role!r} — "
            "this endpoint is missing the admin check"
        )
        assert response.json()["detail"] == "Admin role required"


class TestAdminIsAllowedThrough:
    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_the_role_check_does_not_block_an_admin(self, client_as, method, path):
        """An admin must get past the guard. The handler itself may still fail
        (no database in this app), so anything other than 403 proves the check
        allowed the request through."""
        response = client_as("admin").request(method, _concrete(f"/api/admin{path}"), json={})
        assert response.status_code != 403


class TestRequireAdmin:
    async def test_admin_passes(self):
        user = {"user_id": "u1", "role": "admin", "name": "A"}
        assert await require_admin(user) == user

    @pytest.mark.parametrize("role", ["operator", "viewer", "manager", "", None])
    async def test_every_other_role_is_refused(self, role):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await require_admin({"user_id": "u1", "role": role, "name": "A"})
        assert exc.value.status_code == 403
