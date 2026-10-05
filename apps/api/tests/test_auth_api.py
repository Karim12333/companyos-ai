from typing import Any

import httpx

from tests.conftest import Tenant


def client_for(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def test_signup_creates_organization_from_template(tenant: Tenant) -> None:
    me = await tenant.client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["organizations"][0]["role"] == "owner"
    agents = (await tenant.client.get(tenant.url("/agents"))).json()
    roles = {agent["role_key"] for agent in agents}
    assert {"chief_of_staff", "market_researcher", "reviewer", "executive_reporter", "copywriter"} <= roles
    departments = (await tenant.client.get(tenant.url("/departments"))).json()
    assert len(departments) == 5
    assert all(department["manager_name"] for department in departments)


async def test_login_logout_and_bad_password(app: Any, tenant: Tenant) -> None:
    async with client_for(app) as client:
        bad = await client.post(
            "/api/v1/auth/login", json={"email": tenant.email, "password": "nope-nope-nope"}
        )
        assert bad.status_code == 401
        good = await client.post(
            "/api/v1/auth/login", json={"email": tenant.email, "password": "correct-horse-battery"}
        )
        assert good.status_code == 200
        csrf = good.json()["csrf_token"]
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        assert (await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})).status_code == 204
        assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_duplicate_signup_rejected(app: Any, tenant: Tenant) -> None:
    async with client_for(app) as client:
        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": tenant.email,
                "password": "another-password",
                "full_name": "X",
                "organization_name": "Dup",
            },
        )
        assert response.status_code == 409


async def test_unauthenticated_requests_are_rejected(app: Any, tenant: Tenant) -> None:
    async with client_for(app) as client:
        assert (await client.get(f"/api/v1/orgs/{tenant.org_id}/agents")).status_code == 401


async def test_mutations_require_csrf_token(tenant: Tenant) -> None:
    body = {"title": "Test objective", "instruction": "Do something useful for the company."}
    response = await tenant.client.post(tenant.url("/projects"), json={"name": "No CSRF"})
    assert response.status_code == 403
    response = await tenant.client.post(
        tenant.url("/objectives"), json=body, headers={"X-CSRF-Token": "forged"}
    )
    assert response.status_code == 403


async def test_second_organization_and_template_listing(tenant: Tenant) -> None:
    templates = (await tenant.client.get("/api/v1/orgs/templates")).json()
    assert templates[0]["key"] == "software_ai_company"
    created = await tenant.client.post("/api/v1/orgs", json={"name": "Second Co"}, headers=tenant.headers)
    assert created.status_code == 201
    me = (await tenant.client.get("/api/v1/auth/me")).json()
    assert len(me["organizations"]) == 2
