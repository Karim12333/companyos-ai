import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.events import queue_realtime, record_activity, record_audit
from companyos.models import Agent, Approval, InboxItem, Objective
from companyos.models.enums import (
    ActorType,
    ApprovalStatus,
    InboxCategory,
    RiskLevel,
    Severity,
)


class ApprovalStateError(Exception):
    pass


def objective_link(objective_id: uuid.UUID | None) -> str | None:
    return f"/objectives/{objective_id}" if objective_id else None


async def create_approval(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    agent: Agent,
    action_key: str,
    tool_key: str | None,
    risk_level: RiskLevel,
    title: str,
    summary: str,
    payload: dict[str, Any],
    objective_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    artifact_id: uuid.UUID | None = None,
    preapproved: bool = False,
) -> Approval:
    approval = Approval(
        organization_id=organization_id,
        objective_id=objective_id,
        task_id=task_id,
        agent_id=agent.id,
        artifact_id=artifact_id,
        action_key=action_key,
        tool_key=tool_key,
        risk_level=risk_level,
        title=title,
        summary=summary,
        payload=payload,
    )
    if preapproved:
        # Allowed by organization policy: no CEO decision, but still one tracked action record
        approval.status = ApprovalStatus.APPROVED
        approval.decided_at = datetime.now(UTC)
        approval.decision_note = "Allowed by organization policy"
    session.add(approval)
    await session.flush()
    if preapproved:
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="approval.policy_allowed",
            summary=f"{agent.name}: {title} (allowed by organization policy)",
            objective_id=objective_id,
            agent_id=agent.id,
            task_id=task_id,
            actor_type=ActorType.AGENT,
            data={"approval_id": str(approval.id), "action": action_key},
        )
        return approval
    session.add(
        InboxItem(
            organization_id=organization_id,
            category=InboxCategory.APPROVAL_REQUIRED,
            severity=Severity.HIGH if risk_level == RiskLevel.HUMAN_APPROVAL else Severity.MEDIUM,
            objective_id=objective_id,
            department_id=agent.department_id,
            agent_id=agent.id,
            task_id=task_id,
            approval_id=approval.id,
            artifact_id=artifact_id,
            title=title,
            summary=summary,
            action_required=True,
            link=f"/approvals/{approval.id}",
        )
    )
    await record_activity(
        session,
        organization_id=organization_id,
        event_type="approval.requested",
        summary=f"{agent.name} requested approval: {title}",
        objective_id=objective_id,
        department_id=agent.department_id,
        agent_id=agent.id,
        task_id=task_id,
        actor_type=ActorType.AGENT,
        data={"approval_id": str(approval.id), "action": action_key},
    )
    queue_realtime(session, organization_id, "approval", {"approval_id": str(approval.id)})
    return approval


async def decide_approval(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    approval_id: uuid.UUID,
    approve: bool,
    user_id: uuid.UUID,
    note: str = "",
) -> Approval:
    approval = await session.scalar(
        select(Approval)
        .where(Approval.id == approval_id, Approval.organization_id == organization_id)
        .with_for_update()
    )
    if approval is None:
        raise LookupError("Approval not found")
    if approval.status != ApprovalStatus.PENDING:
        raise ApprovalStateError(f"Approval already {approval.status.value.lower()}")
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.decided_by_user_id = user_id
    approval.decided_at = datetime.now(UTC)
    approval.decision_note = note
    await session.execute(
        update(InboxItem)
        .where(InboxItem.approval_id == approval.id, InboxItem.organization_id == organization_id)
        .values(resolved_at=datetime.now(UTC), is_read=True, action_required=False)
    )
    decision = "approved" if approve else "rejected"
    await record_activity(
        session,
        organization_id=organization_id,
        event_type=f"approval.{decision}",
        summary=f"CEO {decision}: {approval.title}",
        objective_id=approval.objective_id,
        agent_id=approval.agent_id,
        task_id=approval.task_id,
        actor_type=ActorType.USER,
        actor_user_id=user_id,
        data={"approval_id": str(approval.id), "note": note},
    )
    await record_audit(
        session,
        action=f"approval.{decision}",
        organization_id=organization_id,
        actor_type=ActorType.USER,
        actor_user_id=user_id,
        target_type="approval",
        target_id=approval.id,
        details={"action_key": approval.action_key, "note": note},
    )
    queue_realtime(session, organization_id, "approval", {"approval_id": str(approval.id)})
    await session.flush()
    return approval


async def objective_workflow_id(session: AsyncSession, approval: Approval) -> str | None:
    if approval.objective_id is None:
        return None
    return await session.scalar(select(Objective.workflow_id).where(Objective.id == approval.objective_id))
