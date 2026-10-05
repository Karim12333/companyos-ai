"""Approval notification and execution activities."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity

from companyos.db import tenant_scope
from companyos.models import Approval, Escalation, Task
from companyos.models.enums import (
    ApprovalStatus,
    EscalationKind,
    EscalationStatus,
    ExecutionStatus,
    TaskStatus,
)
from companyos.services.escalations import UNKNOWN_OUTCOME_OPTIONS, create_escalation
from companyos.services.notifications import notify_approval_required
from companyos.services.objective_status import refresh_objective_status
from companyos.tools import gateway
from companyos.workflows.activities.shared import ids
from companyos.workflows.types import ApprovalCheck, ApprovalResolution, TaskRef


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
async def resolve_task_approvals(ref: TaskRef) -> ApprovalResolution:
    """Executes approved actions at most once; unknown outcomes go to the CEO instead of a retry."""
    organization_id, _, task_id = ids(ref.organization_id, ref.objective_id, ref.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        approval_ids = [uuid.UUID(value) for value in (task.result or {}).get("approval_ids", [])]
        approvals = (await session.scalars(select(Approval).where(Approval.id.in_(approval_ids)))).all()
        to_execute = [
            a.id
            for a in approvals
            if a.status == ApprovalStatus.APPROVED
            and a.execution_status in (ExecutionStatus.NOT_STARTED, ExecutionStatus.EXECUTING)
        ]
    # Context is rebuilt from each approval record and must match this task
    outcomes = {
        approval_id: await gateway.execute_approved(organization_id, approval_id, expected_task_id=task_id)
        for approval_id in to_execute
    }

    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        approvals = (await session.scalars(select(Approval).where(Approval.id.in_(approval_ids)))).all()
        noted = set(task.execution_metadata.get("approval_notes", []))
        notes = []
        escalation_ids: list[str] = []
        for approval in approvals:
            if approval.execution_status == ExecutionStatus.UNKNOWN:
                escalation_ids.append(str(await _unknown_outcome_escalation(session, task, approval)))
                continue
            if str(approval.id) in noted:
                continue
            if approval.status == ApprovalStatus.REJECTED:
                notes.append(f"CEO rejected: {approval.title}")
            elif approval.execution_status == ExecutionStatus.EXECUTED:
                message = outcomes[approval.id].content if approval.id in outcomes else "executed"
                notes.append(f"Approved action executed: {message[:300]}")
            elif approval.execution_status == ExecutionStatus.FAILED:
                notes.append(f"Approved action failed: {(approval.execution_error or '')[:300]}")
            else:
                continue
            noted.add(str(approval.id))
        if notes:
            task.output_summary = (task.output_summary + "\n\n" + "\n".join(notes)).strip()[:4000]
        task.execution_metadata = {**task.execution_metadata, "approval_notes": sorted(noted)}
        if not escalation_ids:
            task.status = TaskStatus.REVIEW if task.requires_review else TaskStatus.RUNNING
        await refresh_objective_status(session, task.objective_id)
        return ApprovalResolution(escalation_ids=escalation_ids)


async def _unknown_outcome_escalation(session: AsyncSession, task: Task, approval: Approval) -> uuid.UUID:
    # Reuse the open escalation if a retried activity already created it
    existing = await session.scalar(
        select(Escalation.id).where(
            Escalation.approval_id == approval.id, Escalation.status == EscalationStatus.OPEN
        )
    )
    if existing:
        return existing
    escalation = await create_escalation(
        session,
        task=task,
        kind=EscalationKind.ACTION_OUTCOME_UNKNOWN,
        question=(
            f"We could not confirm whether '{approval.title}' was carried out (the worker stopped mid-action). "
            "Please check the external system and tell us what happened."
        ),
        context=approval.summary,
        options=UNKNOWN_OUTCOME_OPTIONS,
        agent_id=approval.agent_id,
        approval_id=approval.id,
    )
    return escalation.id
