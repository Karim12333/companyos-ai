import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.events import queue_realtime, record_activity, record_audit
from companyos.models import Agent, Escalation, InboxItem, Task
from companyos.models.enums import (
    ActorType,
    EscalationKind,
    EscalationStatus,
    InboxCategory,
    Severity,
    TaskStatus,
)
from companyos.services.objective_status import refresh_objective_status

# Every escalation can be answered with guidance or stopped; these are always offered
ANSWER_OPTION = {
    "key": "answer",
    "label": "Answer and continue",
    "description": "Give the agent the missing decision or information and let it continue.",
    "requires_note": True,
}
FAIL_OPTION = {
    "key": "fail",
    "label": "Stop this task",
    "description": "Mark the task as failed. Tasks that depend on it will be blocked.",
    "requires_note": False,
}
REVIEW_EXHAUSTED_OPTIONS = [
    {
        "key": "accept",
        "label": "Accept as is",
        "description": "Complete the task with the current deliverable. It is flagged in the report.",
        "requires_note": False,
    },
    {
        "key": "revise",
        "label": "Revise with my guidance",
        "description": "Send your guidance to the agent for one more revision round.",
        "requires_note": True,
    },
    FAIL_OPTION,
]
UNKNOWN_OUTCOME_OPTIONS = [
    {
        "key": "mark_executed",
        "label": "It happened — mark as executed",
        "description": "I verified the external action took place; do not repeat it.",
        "requires_note": False,
    },
    {
        "key": "retry",
        "label": "It did not happen — execute again",
        "description": "I verified it did not take place; execute it once more.",
        "requires_note": False,
    },
    {
        "key": "abandon",
        "label": "Do not execute",
        "description": "Leave the action unexecuted.",
        "requires_note": False,
    },
]


class EscalationError(Exception):
    pass


def agent_options(proposed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Agent-proposed choices first, then the always-available answer/stop options
    options = [
        {
            "key": f"option_{index + 1}",
            "label": str(item.get("label", ""))[:120],
            "description": str(item.get("description", ""))[:500],
            "requires_note": False,
        }
        for index, item in enumerate(proposed[:4])
        if item.get("label")
    ]
    return [*options, ANSWER_OPTION, FAIL_OPTION]


async def create_escalation(
    session: AsyncSession,
    *,
    task: Task,
    kind: EscalationKind,
    question: str,
    context: str,
    options: list[dict[str, Any]],
    agent_id: uuid.UUID | None,
    approval_id: uuid.UUID | None = None,
) -> Escalation:
    escalation = Escalation(
        organization_id=task.organization_id,
        objective_id=task.objective_id,
        task_id=task.id,
        agent_id=agent_id,
        approval_id=approval_id,
        kind=kind,
        question=question[:4000],
        context=context[:8000],
        options=options,
    )
    session.add(escalation)
    await session.flush()
    task.status = TaskStatus.NEEDS_ATTENTION
    agent = await session.get(Agent, agent_id) if agent_id else None
    session.add(
        InboxItem(
            organization_id=task.organization_id,
            category=InboxCategory.DECISION_REQUIRED,
            severity=Severity.HIGH,
            objective_id=task.objective_id,
            department_id=task.department_id,
            agent_id=agent_id,
            task_id=task.id,
            title=f"Decision required: {task.title}",
            summary=question[:500],
            action_required=True,
            link=f"/escalations/{escalation.id}",
        )
    )
    await record_activity(
        session,
        organization_id=task.organization_id,
        event_type="escalation.created",
        summary=f"{agent.name if agent else 'The platform'} escalated '{task.title}' to the CEO: {question[:140]}",
        objective_id=task.objective_id,
        department_id=task.department_id,
        agent_id=agent_id,
        task_id=task.id,
        actor_type=ActorType.AGENT if agent_id else ActorType.SYSTEM,
        data={"escalation_id": str(escalation.id), "kind": kind.value},
    )
    await record_audit(
        session,
        action="escalation.create",
        organization_id=task.organization_id,
        actor_type=ActorType.AGENT if agent_id else ActorType.SYSTEM,
        actor_agent_id=agent_id,
        target_type="escalation",
        target_id=escalation.id,
        details={"kind": kind.value, "task_id": str(task.id)},
    )
    queue_realtime(session, task.organization_id, "escalation", {"escalation_id": str(escalation.id)})
    await refresh_objective_status(session, task.objective_id)
    return escalation


async def resolve_escalation(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    escalation_id: uuid.UUID,
    option: str,
    note: str,
    user_id: uuid.UUID,
) -> Escalation:
    escalation = await session.scalar(
        select(Escalation)
        .where(Escalation.id == escalation_id, Escalation.organization_id == organization_id)
        .with_for_update()
    )
    if escalation is None:
        raise LookupError("Escalation not found")
    if escalation.status != EscalationStatus.OPEN:
        raise EscalationError(f"Escalation already {escalation.status.value.lower()}")
    chosen = next((item for item in escalation.options if item.get("key") == option), None)
    if chosen is None:
        raise EscalationError("Unknown option for this escalation")
    if chosen.get("requires_note") and not note.strip():
        raise EscalationError("This option needs a note with your guidance")
    escalation.status = EscalationStatus.RESOLVED
    escalation.resolution_option = option
    escalation.resolution_note = note.strip()[:4000]
    escalation.resolved_by_user_id = user_id
    escalation.resolved_at = datetime.now(UTC)
    await session.execute(
        update(InboxItem)
        .where(
            InboxItem.organization_id == organization_id,
            InboxItem.link == f"/escalations/{escalation.id}",
        )
        .values(resolved_at=datetime.now(UTC), is_read=True, action_required=False)
    )
    await record_activity(
        session,
        organization_id=organization_id,
        event_type="escalation.resolved",
        summary=f"CEO decided: {chosen.get('label')}" + (f" — {note.strip()[:140]}" if note.strip() else ""),
        objective_id=escalation.objective_id,
        task_id=escalation.task_id,
        agent_id=escalation.agent_id,
        actor_type=ActorType.USER,
        actor_user_id=user_id,
        data={"escalation_id": str(escalation.id), "option": option},
    )
    await record_audit(
        session,
        action="escalation.resolve",
        organization_id=organization_id,
        actor_type=ActorType.USER,
        actor_user_id=user_id,
        target_type="escalation",
        target_id=escalation.id,
        details={"option": option},
    )
    queue_realtime(session, organization_id, "escalation", {"escalation_id": str(escalation.id)})
    await session.flush()
    return escalation


async def cancel_open_escalations(session: AsyncSession, objective_id: uuid.UUID) -> None:
    await session.execute(
        update(Escalation)
        .where(Escalation.objective_id == objective_id, Escalation.status == EscalationStatus.OPEN)
        .values(status=EscalationStatus.CANCELLED)
    )
