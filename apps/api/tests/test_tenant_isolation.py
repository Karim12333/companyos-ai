import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from companyos.db import TenantContext, session_scope, tenant_scope
from companyos.models import Agent, Department, Objective
from tests.conftest import Tenant


async def test_member_cannot_access_another_organization(tenant: Tenant, other_tenant: Tenant) -> None:
    foreign = f"/api/v1/orgs/{other_tenant.org_id}"
    for path in [
        "",
        "/headquarters",
        "/agents",
        "/objectives",
        "/artifacts",
        "/approvals",
        "/inbox",
        "/knowledge/memory",
        "/integrations",
        "/settings",
        "/analytics",
        "/activity",
    ]:
        response = await tenant.client.get(foreign + path)
        assert response.status_code == 404, path


async def test_object_ids_from_another_tenant_are_not_reachable(tenant: Tenant, other_tenant: Tenant) -> None:
    created = await other_tenant.client.post(
        other_tenant.url("/projects"), json={"name": "Secret project"}, headers=other_tenant.headers
    )
    project_id = created.json()["id"]
    other_agents = (await other_tenant.client.get(other_tenant.url("/agents"))).json()
    # IDOR: use our own org path with their object ids
    assert (await tenant.client.get(tenant.url(f"/projects/{project_id}"))).status_code == 404
    assert (await tenant.client.get(tenant.url(f"/agents/{other_agents[0]['id']}"))).status_code == 404
    patch = await tenant.client.patch(
        tenant.url(f"/agents/{other_agents[0]['id']}"), json={"name": "Hijacked"}, headers=tenant.headers
    )
    assert patch.status_code == 404
    listing = (await tenant.client.get(tenant.url("/projects"))).json()
    assert all(item["id"] != project_id for item in listing)


async def test_row_level_security_hides_other_tenants(tenant: Tenant, other_tenant: Tenant) -> None:
    org_a, org_b = uuid.UUID(tenant.org_id), uuid.UUID(other_tenant.org_id)
    async with tenant_scope(org_a) as session:
        # No WHERE clause on purpose: only RLS restricts these queries
        organizations = set(await session.scalars(select(Agent.organization_id).distinct()))
        assert organizations == {org_a}
        departments = await session.scalar(select(func.count(Department.id)))
        assert departments == 5
        raw = await session.execute(
            text("SELECT count(*) FROM agents WHERE organization_id = :b"), {"b": org_b}
        )
        assert raw.scalar() == 0


async def test_row_level_security_blocks_cross_tenant_writes(tenant: Tenant, other_tenant: Tenant) -> None:
    with pytest.raises(DBAPIError):
        async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
            session.add(
                Objective(organization_id=uuid.UUID(other_tenant.org_id), title="Injected", instruction="x")
            )
            await session.flush()


async def test_no_tenant_context_sees_nothing(tenant: Tenant) -> None:
    async with session_scope(TenantContext()) as session:
        assert await session.scalar(select(func.count(Agent.id))) == 0
