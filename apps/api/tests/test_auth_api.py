import uuid
from typing import Any

import httpx
from sqlalchemy import select

from companyos.db import tenant_scope
from companyos.models import Agent, AgentRelationship
from companyos.services.organizations import instantiate_template
from companyos.templates.software_company import SOFTWARE_COMPANY
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


async def test_template_sync_is_idempotent_and_additive(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    async with tenant_scope(organization_id) as session:
        agents = {agent.role_key: agent for agent in (await session.scalars(select(Agent))).all()}
        assert {"fullstack_engineer", "ai_engineer", "qa_engineer"} <= set(agents)
        architect = agents["technical_architect"]
        architect.system_instructions = "Customized by the CEO"
        await session.delete(agents["qa_engineer"])
    async with tenant_scope(organization_id) as session:
        await instantiate_template(session, organization_id, SOFTWARE_COMPANY)
        await instantiate_template(session, organization_id, SOFTWARE_COMPANY)
    async with tenant_scope(organization_id) as session:
        agents = {agent.role_key: agent for agent in (await session.scalars(select(Agent))).all()}
        assert len(agents) == len(SOFTWARE_COMPANY.agents)
        assert agents["technical_architect"].system_instructions == "Customized by the CEO"
        delegates = set(
            await session.scalars(
                select(AgentRelationship.related_agent_id).where(
                    AgentRelationship.agent_id == agents["technical_architect"].id
                )
            )
        )
        assert agents["qa_engineer"].id in delegates
        assert agents["qa_engineer"].manager_agent_id == agents["technical_architect"].id
