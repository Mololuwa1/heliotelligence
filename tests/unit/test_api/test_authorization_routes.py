"""Whole-app policy and indirect-resource authorization, with no external services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi import routing as fastapi_routing
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from heliotelligence.api import app as app_module
from heliotelligence.api import auth
from heliotelligence.api.routers import admin, alerts, health
from heliotelligence.db.session import get_db
from tests.unit.test_api import test_authorization as support

SITE_A, SITE_B, UID = support.SITE_A, support.SITE_B, support.UID
claims = support.claims
db = support.db

# Every application resource must have an explicit policy. Framework-generated
# schema/docs are public API metadata, not application data routes.
POLICIES = {
    ("GET", "/health"): "public",
    ("GET", "/api/v1/admin/me"): "identity",
    ("GET", "/api/v1/admin/sites"): "platform",
    ("POST", "/api/v1/admin/sites"): "platform",
    ("POST", "/api/v1/admin/sites/{site_id}/upload"): "platform",
    ("POST", "/api/v1/admin/sites/{site_id}/access"): "platform",
    ("GET", "/api/v1/ingest/status"): "platform",
    ("GET", "/api/v1/expected-energy/{site_id}"): "read",
    ("GET", "/api/v1/benchmarking/{site_id}"): "read",
    ("GET", "/api/v1/analysis/{site_id}/degradation"): "read",
    ("GET", "/api/v1/analysis/{site_id}/anomalies"): "read",
    ("GET", "/api/v1/analysis/{site_id}/string-health"): "read",
    ("GET", "/api/v1/analysis/{site_id}/inverter-health"): "read",
    ("POST", "/api/v1/reports/{site_id}"): "read",
    ("GET", "/api/v1/alerts/{site_id}"): "read",
    ("GET", "/api/v1/sites/{site_id}/layout"): "read",
    ("GET", "/api/v1/sites/{site_id}/geometry"): "read",
    ("POST", "/api/v1/backfill/{site_id}"): "site_admin",
    ("POST", "/api/v1/alerts/{alert_id}/acknowledge"): "alert_admin",
}


@pytest.fixture
def application() -> FastAPI:
    return app_module.create_app()


def routes(application: FastAPI) -> dict[tuple[str, str], Any]:
    # Recent FastAPI includes routers lazily. Its public iterator exposes the
    # effective path/dependant for this application inclusion, not the shared
    # original router. Older supported releases expose APIRoutes directly.
    contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    candidates = contexts(application.routes) if contexts is not None else application.routes
    actual = {}
    for route in candidates:
        if not isinstance(getattr(route, "original_route", route), APIRoute):
            continue
        for method in route.methods:
            key = (method, route.path)
            assert key not in actual, f"Duplicate application route: {key}"
            actual[key] = route
    return actual


def dependencies(node: Any) -> set[Any]:
    return {node.call}.union(*(dependencies(child) for child in node.dependencies))


@pytest.fixture
def client(
    application: FastAPI, db: support.Database, claims: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    async def connection() -> AsyncIterator[Any]:
        yield db

    application.dependency_overrides[get_db] = connection
    monkeypatch.setattr(admin, "get_session_factory", lambda: db.session)
    monkeypatch.setattr(health, "get_db_version", AsyncMock(return_value="unit-test-db"))
    # No lifespan: it syncs configured sites and owns background scheduler jobs.
    transport = TestClient(application)
    try:
        yield transport
    finally:
        transport.close()
        application.dependency_overrides.clear()


def request(
    client: TestClient,
    key: tuple[str, str],
    *,
    authenticated: bool = True,
    site: str = SITE_A,
    extra_headers: Any = None,
) -> Any:
    method, path = key
    headers = {"Authorization": "Bearer valid"} if authenticated else {}
    headers.update(extra_headers or {})
    options: dict[str, Any] = dict(
        headers=headers, params={"start": "2024-06-21T10:00:00Z", "end": "2024-06-21T11:00:00Z"}
    )
    if path == "/api/v1/admin/sites":
        options["json"] = {"name": "Test", "latitude": 52, "longitude": 1, "capacity_kwp": 100}
    elif path.endswith("/access"):
        options["json"] = {"uid": "target-user", "role": "viewer"}
    elif path.endswith("/upload"):
        options["files"] = {"file": ("test.csv", b"test", "text/csv")}
    return client.request(
        method, path.replace("{site_id}", site).replace("{alert_id}", "7"), **options
    )


def assert_complete_route_policy(application: FastAPI) -> None:
    actual = routes(application)
    assert set(actual) == set(POLICIES), "New routes require an explicit reviewed policy"
    expected = {
        "identity": auth.get_current_user,
        "platform": auth.require_platform_admin,
        "read": auth.require_site_access,
        "site_admin": auth.require_site_admin,
        "alert_admin": alerts.require_alert_site_admin,
    }
    for key, policy in POLICIES.items():
        calls = dependencies(actual[key].dependant)
        if policy == "public":
            assert auth.get_current_user not in calls
        else:
            assert auth.get_current_user in calls
            assert expected[policy] in calls
        if policy == "identity":
            assert auth.require_platform_admin not in calls


def test_complete_route_policy(application: FastAPI) -> None:
    assert_complete_route_policy(application)


@pytest.mark.parametrize("key,policy", list(POLICIES.items()))
@pytest.mark.parametrize("role", ["none", "viewer", "admin", "platform"])
def test_http_route_role_matrix(
    application: FastAPI,
    client: TestClient,
    db: support.Database,
    claims: Any,
    monkeypatch: pytest.MonkeyPatch,
    key: tuple[str, str],
    policy: str,
    role: str,
) -> None:
    if role in ("viewer", "admin"):
        db.grant(role)
    claims["platform_admin"] = role == "platform"
    endpoint = AsyncMock(
        side_effect=HTTPException(status_code=418, detail="authorized business boundary")
    )
    monkeypatch.setattr(routes(application)[key].dependant, "call", endpoint)
    response = request(client, key)
    allowed = (
        policy in ("identity", "public")
        or role == "platform"
        or (policy == "read" and role in ("viewer", "admin"))
        or (policy in ("site_admin", "alert_admin") and role == "admin")
    )
    assert response.status_code == (418 if allowed else 403), (key, role, response.text)
    if allowed:
        endpoint.assert_awaited_once()
    else:
        endpoint.assert_not_awaited()
    if role == "platform":
        assert not any("user_site_access" in sql for sql, _ in db.calls)


@pytest.mark.parametrize("key", [key for key, policy in POLICIES.items() if policy != "public"])
def test_all_protected_resources_require_authentication(
    client: TestClient, db: support.Database, claims: Any, key: tuple[str, str]
) -> None:
    response = request(client, key, authenticated=False)
    assert response.status_code == 401
    assert db.calls == []
    auth.firebase_auth.verify_id_token.assert_not_called()


@pytest.mark.parametrize(
    "key", [key for key, policy in POLICIES.items() if policy in ("read", "site_admin")]
)
def test_cross_site_denial_precedes_business_queries(
    application: FastAPI,
    client: TestClient,
    db: support.Database,
    claims: Any,
    monkeypatch: pytest.MonkeyPatch,
    key: tuple[str, str],
) -> None:
    db.grant("admin", SITE_A)
    endpoint = AsyncMock(side_effect=AssertionError("protected business logic accessed"))
    monkeypatch.setattr(routes(application)[key].dependant, "call", endpoint)
    response = request(client, key, site=SITE_B)
    assert response.status_code == 403
    endpoint.assert_not_awaited()
    assert len(db.calls) == 1
    assert "SELECT role FROM user_site_access" in db.calls[0][0]
    assert db.calls[0][1] == {"uid": UID, "site_id": SITE_B}


def test_client_site_query_cannot_override_path_site(
    client: TestClient, db: support.Database
) -> None:
    db.grant("admin", SITE_A)
    response = client.get(
        f"/api/v1/expected-energy/{SITE_B}",
        headers={"Authorization": "Bearer valid"},
        params={"site_id": SITE_A, "start": "2024-06-21T10:00:00Z", "end": "2024-06-21T11:00:00Z"},
    )
    assert response.status_code == 403
    assert db.calls[-1][1]["site_id"] == SITE_B


def test_retired_key_cannot_elevate_site_admin(
    application: FastAPI, client: TestClient, db: support.Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.grant("admin")
    monkeypatch.setenv("ADMIN_API_KEY", "retired-test-key")
    endpoint = AsyncMock(side_effect=AssertionError("platform operation accessed"))
    key = ("GET", "/api/v1/admin/sites")
    monkeypatch.setattr(routes(application)[key].dependant, "call", endpoint)
    response = request(client, key, extra_headers={"X-Admin-Key": "retired-test-key"})
    assert response.status_code == 403
    endpoint.assert_not_awaited()
    assert not hasattr(auth, "get_admin_user")


@pytest.mark.parametrize("platform", [False, True])
def test_me_is_authenticated_identity_not_admin_only(
    client: TestClient, claims: Any, platform: bool
) -> None:
    claims["platform_admin"] = platform
    response = client.get("/api/v1/admin/me", headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    assert response.json() == {
        "uid": UID,
        "email": "test@example.invalid",
        "platform_admin": platform,
    }


def test_health_is_public(client: TestClient, db: support.Database, claims: Any) -> None:
    assert client.get("/health").status_code == 200
    auth.firebase_auth.verify_id_token.assert_not_called()
    health.get_db_version.assert_awaited_once_with(db)


@pytest.mark.parametrize(
    "role,allowed",
    [
        ("admin", True),
        ("viewer", False),
        ("other_admin", False),
        ("owner", False),
        ("platform", True),
    ],
)
def test_acknowledgement_uses_alert_canonical_site_before_mutation(
    client: TestClient,
    db: support.Database,
    claims: Any,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    allowed: bool,
) -> None:
    claims["platform_admin"] = role == "platform"
    if role not in ("platform", "other_admin"):
        db.grant(role, SITE_A)
    elif role == "other_admin":
        db.grant("admin", SITE_B)

    def verify(token: str) -> Any:
        db.events.append(("authenticated",))
        return claims

    monkeypatch.setattr(auth.firebase_auth, "verify_id_token", Mock(side_effect=verify))
    response = client.post(
        "/api/v1/alerts/7/acknowledge",
        headers={"Authorization": "Bearer valid"},
        params={"site_id": SITE_B},
    )
    assert response.status_code == (200 if allowed else 403)
    assert db.events[:2] == [("authenticated",), ("locate_alert", 7)]
    assert db.alert.acknowledged == allowed
    assert db.commits == int(allowed)
    mutations = [i for i, event in enumerate(db.events) if event[0] == "mutate_alert"]
    if not allowed:
        assert not mutations
        assert not any(e[0] == "refresh" for e in db.events)
    elif role == "admin":
        authorization = [
            i for i, e in enumerate(db.events) if e[0] == "sql" and "user_site_access" in e[1]
        ]
        assert authorization[0] < mutations[0]
    if role != "platform":
        assert db.calls[-1][1] == {"uid": UID, "site_id": db.alert.site_id}


def test_unknown_alert_is_404_without_mutation(client: TestClient, db: support.Database) -> None:
    response = client.post(
        "/api/v1/alerts/999/acknowledge", headers={"Authorization": "Bearer valid"}
    )
    assert response.status_code == 404
    assert db.commits == 0 and not db.alert.acknowledged


@pytest.mark.parametrize("role", ["viewer", "admin"])
def test_platform_grant_valid_role_and_upsert(
    client: TestClient, db: support.Database, claims: Any, role: str
) -> None:
    claims["platform_admin"] = True
    db.grant("viewer", SITE_A, "target-user")
    response = client.post(
        f"/api/v1/admin/sites/{SITE_A}/access",
        headers={"Authorization": "Bearer valid"},
        json={"uid": "target-user", "role": role},
    )
    assert response.status_code == 200
    assert db.connection.execute(
        "SELECT role FROM user_site_access WHERE uid=? AND site_id=?", ("target-user", SITE_A)
    ).fetchone() == (role,)
    assert db.commits == 1
    assert db.calls[0][1] == {"site_id": SITE_A}
    assert db.calls[-1][1] == {"uid": "target-user", "site_id": SITE_A, "role": role}


@pytest.mark.parametrize(
    "body",
    [
        {"uid": "target", "role": role}
        for role in ["owner", "platform_admin", "Admin", "admin ", None, 1]
    ]
    + [{"uid": uid, "role": "viewer"} for uid in ["", " ", None, 1]],
)
def test_invalid_grant_request_rejected_before_write(
    client: TestClient, db: support.Database, claims: Any, body: Any
) -> None:
    claims["platform_admin"] = True
    response = client.post(
        f"/api/v1/admin/sites/{SITE_A}/access", headers={"Authorization": "Bearer valid"}, json=body
    )
    assert response.status_code == 422
    assert db.calls == [] and db.commits == 0


def test_nonplatform_site_admin_cannot_grant_self_access(
    client: TestClient, db: support.Database
) -> None:
    db.grant("admin")
    response = client.post(
        f"/api/v1/admin/sites/{SITE_A}/access",
        headers={"Authorization": "Bearer valid"},
        json={"uid": UID, "role": "admin"},
    )
    assert response.status_code == 403
    assert db.calls == [] and db.commits == 0


@pytest.mark.parametrize("site", [SITE_B.replace("b", "c"), "unknown-site"])
def test_grant_requires_existing_persisted_site(
    client: TestClient, db: support.Database, claims: Any, site: str
) -> None:
    claims["platform_admin"] = True
    response = client.post(
        f"/api/v1/admin/sites/{site}/access",
        headers={"Authorization": "Bearer valid"},
        json={"uid": "target", "role": "viewer"},
    )
    assert response.status_code == 404
    assert len(db.calls) == 1 and db.commits == 0
    assert "INSERT" not in db.calls[0][0]


def test_no_browser_admin_secret_or_backend_key_authority() -> None:
    root = Path(__file__).resolve().parents[3]
    frontend = [
        p
        for p in (root / "frontend/src").rglob("*")
        if p.is_file() and p.suffix in {".js", ".jsx", ".ts", ".tsx"}
    ]
    config = [
        root / p
        for p in [
            "frontend/.env.staging.example",
            ".github/workflows/ci.yml",
            "cloudbuild.yaml",
            "deploy/cloudbuild.staging.yaml",
        ]
    ]
    for path in frontend + config:
        content = path.read_text()
        assert "VITE_ADMIN_KEY" not in content, path
        assert "X-Admin-Key" not in content, path
        assert "ADMIN_API_KEY" not in content, path
    for path in (root / "src/heliotelligence/api").rglob("*.py"):
        assert "ADMIN_API_KEY" not in path.read_text(), path
        assert "X-Admin-Key" not in path.read_text(), path


def test_factory_instances_are_isolated() -> None:
    production_overrides = app_module.app.dependency_overrides.copy()
    first, second = app_module.create_app(), app_module.create_app()
    assert first is not second and first.router is not second.router
    assert first.routes is not second.routes
    assert first.dependency_overrides is not second.dependency_overrides
    assert first.dependency_overrides is not app_module.app.dependency_overrides
    first.dependency_overrides[auth.get_current_user] = lambda: {"uid": "test"}
    assert not second.dependency_overrides
    assert app_module.app.dependency_overrides == production_overrides
    key = ("GET", "/api/v1/expected-energy/{site_id}")
    a, b, production = routes(first)[key], routes(second)[key], routes(app_module.app)[key]
    assert a.dependant is not b.dependant and a.dependant is not production.dependant
    original = b.dependant.call
    a.dependant.call = AsyncMock()
    assert b.dependant.call is original
    assert production.dependant.call is original


def test_factory_and_production_have_identical_canonical_policies() -> None:
    for application in (app_module.create_app(), app_module.create_app(), app_module.app):
        assert_complete_route_policy(application)
        openapi = application.openapi()
        documented = {
            (method.upper(), path)
            for path, methods in openapi["paths"].items()
            for method in methods
        }
        assert documented == set(routes(application)) == set(POLICIES)


def test_factory_retains_metadata_and_cors() -> None:
    for application in (app_module.create_app(), app_module.app):
        assert application.title == "Heliotelligence"
        assert (
            application.description
            == "Solar farm digital twin and performance benchmarking platform"
        )
        assert application.version == "0.1.0"
        assert len(application.user_middleware) == 1
        middleware = application.user_middleware[0]
        assert middleware.cls is app_module.CORSMiddleware
        assert middleware.kwargs == {
            "allow_origins": app_module.settings.cors_origin_list,
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }


def test_mutated_predecessor_instance_cannot_pollute_next_policy_case() -> None:
    predecessor = app_module.create_app()
    predecessor.router.routes.clear()
    predecessor.dependency_overrides[auth.get_current_user] = lambda: {"uid": "test"}
    following = app_module.create_app()
    assert not following.dependency_overrides
    assert_complete_route_policy(following)
    assert_complete_route_policy(app_module.app)


def test_policy_detects_new_unreviewed_application_route(application: FastAPI) -> None:
    async def unreviewed() -> dict[str, str]:
        return {"test": "unreviewed"}

    application.add_api_route("/api/v1/unreviewed", unreviewed, methods=["GET"])
    with pytest.raises(AssertionError, match="New routes require an explicit reviewed policy"):
        assert_complete_route_policy(application)
    assert ("GET", "/api/v1/unreviewed") not in routes(app_module.create_app())


def test_endpoint_replacement_affects_only_its_application() -> None:
    first, second = app_module.create_app(), app_module.create_app()
    for application in (first, second):
        application.dependency_overrides[auth.get_current_user] = lambda: {
            "uid": "isolated-user",
            "email": None,
            "platform_admin": False,
        }
    key = ("GET", "/api/v1/admin/me")
    routes(first)[key].dependant.call = AsyncMock(
        side_effect=HTTPException(status_code=418, detail="only first app")
    )
    a, b = TestClient(first), TestClient(second)
    try:
        assert a.get(key[1]).status_code == 418
        response = b.get(key[1])
        assert response.status_code == 200
        assert response.json() == {
            "uid": "isolated-user",
            "email": None,
            "platform_admin": False,
        }
    finally:
        a.close()
        b.close()
        first.dependency_overrides.clear()
        second.dependency_overrides.clear()
