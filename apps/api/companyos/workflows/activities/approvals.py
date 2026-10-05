"""Approval notification and execution activities."""

import uuid

from sqlalchemy import select
from temporalio import activity

from companyos.db import tenant_scope
from companyos.models import (
    Agent,
    Approval,
    Task,
)
from companyos.models.enums import (
    ApprovalStatus,
    TaskStatus,
)
from companyos.services.integrations import resolve_ai
from companyos.services.notifications import notify_approval_required
from companyos.tools import gateway
from companyos.tools.registry import ToolContext
from companyos.workflows.activities.shared import (
    ids,
)
from companyos.workflows.types import (
    ApprovalCheck,
    TaskRef,
)


@activity.defn(name="notify_approvals")
async def notify_approvals(check: ApprovalCheck) -> None:
    organization_id = uuid.UUID(check.organization_id)
    async with tenant_scope(organization_id) as session:
        for approval_id in check.approval_ids:
            await notify_approval_required(session, organization_id, uuid.UUID(approval_id))


@activity.defn(name="decided_approvals")
async def decided_approvals(check: ApprovalCheck) -> list[str]:
    organization_id = uuid.UUID(check.organization_id)
    async with tenant_scope(organization_id) as session:
        rows = await session.scalars(
            select(Approval.id).where(
                Approval.id.in_([uuid.UUID(value) for value in check.approval_ids]),
                Approval.status != ApprovalStatus.PENDING,
            )
        )
        return [str(row) for row in rows]


@activity.defn(name="resolve_task_approvals")
async def resolve_task_approvals(ref: TaskRef) -> None:
    organization_id, objective_id, task_id = ids(ref.organization_id, ref.objective_id, ref.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        approval_ids = [uuid.UUID(value) for value in (task.result or {}).get("approval_ids", [])]
        approvals = (await session.scalars(select(Approval).where(Approval.id.in_(approval_ids)))).all()
        agent = await session.get(Agent, task.assigned_agent_id) if task.assigned_agent_id else None
        ai = await resolve_ai(session, organization_id)
        pending_execution = [
            a.id for a in approvals if a.status == ApprovalStatus.APPROVED and a.executed_at is None
        ]
        rejected = [a.title for a in approvals if a.status == ApprovalStatus.REJECTED]
        context = ToolContext(
            organization_id=organization_id,
            agent_id=agent.id if agent else uuid.uuid4(),
            agent_role_key=agent.role_key if agent else "unknown",
            objective_id=objective_id,
            task_id=task_id,
            task_run_id=None,
            llm=ai.provider,
            embedding_model=ai.embedding_model,
        )
    notes = []
    for approval_id in pending_execution:
        outcome = await gateway.execute_approved(context, approval_id)
        notes.append(f"Approved action executed: {outcome.content[:300]}")
    notes += [f"CEO rejected: {title}" for title in rejected]
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        if notes:
            task.output_summary = (task.output_summary + "\n\n" + "\n".join(notes)).strip()[:4000]
        task.status = TaskStatus.REVIEW if task.requires_review else TaskStatus.RUNNING
