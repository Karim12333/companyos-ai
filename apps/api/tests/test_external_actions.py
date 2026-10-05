import dataclasses
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client

from companyos.db import tenant_scope
from companyos.models import ActivityEvent, Agent, Approval, AuditLog, Objective, Task
from companyos.models.enums import ExecutionStatus, RiskLevel
from companyos.services.approvals import create_approval, decide_approval
from companyos.tools import gateway
from companyos.tools.registry import TOOL_REGISTRY, ToolContext, ToolResult
from tests.conftest import Tenant
from tests.workflow_support import TERMINAL, create, pending_approvals, wait_for


async def approved_action(tenant: Tenant, approve: bool | None = True) -> tuple[uuid.UUID, uuid.UUID]:
    """Creates objective + copywriter task + a social post approval; returns (approval_id, task_id)."""
    organization_id = uuid.UUID(tenant.org_id)
    async with tenant_scope(organization_id) as session:
        agent = await session.scalar(select(Agent).where(Agent.role_key == "copywriter"))
        assert agent is not None
        objective = Objective(organization_id=organization_id, title="Launch", instruction="Launch it")
        session.add(objective)
        await session.flush()
        task = Task(
            organization_id=organization_id,
            objective_id=objective.id,
            assigned_agent_id=agent.id,
            plan_key="launch_copy",
            role_key="copywriter",
            title="Launch copy",
            instructions="Write and post",
        )
        session.add(task)
        await session.flush()
        approval = await create_approval(
            session,
            organization_id=organization_id,
            agent=agent,
            action_key="publish_social_post",
            tool_key="publish_social_post",
            risk_level=RiskLevel.HUMAN_APPROVAL,
            title="Publish post",
            summary="Post to linkedin",
            payload={"arguments": {"platform": "linkedin", "content": "We launched today."}},
            objective_id=objective.id,
            task_id=task.id,
        )
        if approve is not None:
            await decide_approval(
                session,
                organization_id=organization_id,
                approval_id=approval.id,
                approve=approve,
                user_id=uuid.UUID(tenant.user_id),
            )
        return approval.id, task.id


async def published_count(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count(ActivityEvent.id)).where(ActivityEvent.event_type == "integration.social_published")
    )
    return int(count or 0)


async def test_approved_action_executes_exactly_once(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    approval_id, task_id = await approved_action(tenant)
    first = await gateway.execute_approved(organization_id, approval_id, expected_task_id=task_id)
    second = await gateway.execute_approved(organization_id, approval_id, expected_task_id=task_id)
    assert first.status == "executed"
    assert (second.status, second.content) == ("executed", "Already executed")
    async with tenant_scope(organization_id) as session:
        approval = await session.get(Approval, approval_id)
        assert approval is not None
        assert approval.execution_status == ExecutionStatus.EXECUTED
        assert approval.execution_attempts == 1
        assert await published_count(session) == 1


async def test_crash_after_external_call_is_never_repeated(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    approval_id, task_id = await approved_action(tenant)
    async with tenant_scope(organization_id) as session:
        # Phase 1 committed, then the worker died before recording the result
        await session.execute(
            update(Approval)
            .where(Approval.id == approval_id)
            .values(execution_status=ExecutionStatus.EXECUTING)
        )
    outcome = await gateway.execute_approved(organization_id, approval_id, expected_task_id=task_id)
    assert outcome.status == "unknown"
    async with tenant_scope(organization_id) as session:
        approval = await session.get(Approval, approval_id)
        assert approval is not None and approval.execution_status == ExecutionStatus.UNKNOWN
        assert await published_count(session) == 0
    again = await gateway.execute_approved(organization_id, approval_id, expected_task_id=task_id)
    assert again.status == "unknown"


async def test_provider_idempotent_tool_is_resent_with_same_key(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys: list[str] = []

    async def idempotent_publish(ctx: ToolContext, session: AsyncSession, args: Any) -> ToolResult:
        keys.append(ctx.extra["idempotency_key"])
        return ToolResult(content="published")

    original = TOOL_REGISTRY["publish_social_post"]
    monkeypatch.setitem(
        TOOL_REGISTRY,
        "publish_social_post",
        dataclasses.replace(original, handler=idempotent_publish, provider_idempotent=True),
    )
    organization_id = uuid.UUID(tenant.org_id)
    approval_id, task_id = await approved_action(tenant)
    async with tenant_scope(organization_id) as session:
        await session.execute(
            update(Approval)
            .where(Approval.id == approval_id)
            .values(execution_status=ExecutionStatus.EXECUTING)
        )
    outcome = await gateway.execute_approved(organization_id, approval_id, expected_task_id=task_id)
    async with tenant_scope(organization_id) as session:
        approval = await session.get(Approval, approval_id)
        assert approval is not None
    assert outcome.status == "executed"
    assert keys == [approval.idempotency_key]


async def test_execution_context_must_match_the_approval(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    approval_id, task_id = await approved_action(tenant)
    wrong_task = await gateway.execute_approved(organization_id, approval_id, expected_task_id=uuid.uuid4())
    assert wrong_task.status == "denied"
    async with tenant_scope(organization_id) as session:
        reviewer = await session.scalar(select(Agent).where(Agent.role_key == "reviewer"))
        assert reviewer is not None
        # Tampered record: approval claims another agent than the one assigned to the task
        await session.execute(update(Approval).where(Approval.id == approval_id).values(agent_id=reviewer.id))
    tampered = await gateway.execute_approved(organization_id, approval_id, expected_task_id=task_id)
    assert tampered.status == "denied"
    async with tenant_scope(organization_id) as session:
        audits = await session.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.action == "approval.context_mismatch")
        )
        assert audits == 2
        assert await published_count(session) == 0


async def test_other_tenant_cannot_execute_approval(tenant: Tenant, other_tenant: Tenant) -> None:
    approval_id, task_id = await approved_action(tenant)
    outcome = await gateway.execute_approved(
        uuid.UUID(other_tenant.org_id), approval_id, expected_task_id=task_id
    )
    assert (outcome.status, outcome.content) == ("denied", "Approval not found")


async def test_rejected_or_pending_approvals_never_execute(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    rejected, rejected_task = await approved_action(tenant, approve=False)
    pending, pending_task = await approved_action(tenant, approve=None)
    assert (await gateway.execute_approved(organization_id, rejected, rejected_task)).status == "denied"
    assert (await gateway.execute_approved(organization_id, pending, pending_task)).status == "denied"
    async with tenant_scope(organization_id) as session:
        assert await published_count(session) == 0


async def test_worker_crash_during_external_action_escalates_instead_of_duplicating(
    temporal: Client, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def crashing_publish(ctx: ToolContext, session: AsyncSession, args: Any) -> ToolResult:
        raise RuntimeError("worker crashed after calling the provider")

    original = TOOL_REGISTRY["publish_social_post"]
    monkeypatch.setitem(
        TOOL_REGISTRY, "publish_social_post", dataclasses.replace(original, handler=crashing_publish)
    )
    objective_id = await create(tenant)
    waiting = await wait_for(tenant, objective_id, lambda d: bool(pending_approvals(d)))
    approval = pending_approvals(waiting)[0]
    await tenant.client.post(
        tenant.url(f"/approvals/{approval['id']}/decision"), json={"approve": True}, headers=tenant.headers
    )
    escalated = await wait_for(
        tenant,
        objective_id,
        lambda d: any(
            e["kind"] == "action_outcome_unknown" and e["status"] == "OPEN" for e in d["escalations"]
        ),
    )
    escalation = next(e for e in escalated["escalations"] if e["kind"] == "action_outcome_unknown")
    assert escalation["approval_id"] == approval["id"]
    response = await tenant.client.post(
        tenant.url(f"/escalations/{escalation['id']}/resolve"),
        json={"option": "mark_executed"},
        headers=tenant.headers,
    )
    assert response.status_code == 200
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    final = next(a for a in done["approvals"] if a["id"] == approval["id"])
    assert final["execution_status"] == "EXECUTED"
    assert final["execution_attempts"] == 1
