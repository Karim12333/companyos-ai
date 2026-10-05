"""Helpers shared by all objective workflow activities."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.events import record_activity
from companyos.models import (
    Agent,
    AgentMessage,
    InboxItem,
    OrganizationPreference,
    Task,
    TaskDependency,
)
from companyos.models.enums import (
    ActorType,
    AgentStatus,
    ErrorCategory,
    InboxCategory,
    MessageKind,
    Severity,
    TaskStatus,
)
from companyos.services.integrations import ResolvedAI
from companyos.services.objective_status import refresh_objective_status

MAX_ATTEMPTS = 3
NON_RETRYABLE = "NonRetryableTaskError"
ACTIVE_TASK_STATES = {TaskStatus.RUNNING, TaskStatus.REVIEW, TaskStatus.WAITING_FOR_APPROVAL}


def now() -> datetime:
    return datetime.now(UTC)


def ids(*values: str) -> list[uuid.UUID]:
    return [uuid.UUID(value) for value in values]


def model_for(agent: Agent | None, ai: ResolvedAI) -> str:
    if ai.source in ("mock", "override"):
        return ai.default_model
    if agent and agent.model:
        return agent.model
    return ai.premium_model if agent and agent.use_premium_model else ai.default_model


async def agent_by_role(session: AsyncSession, organization_id: uuid.UUID, role_key: str) -> Agent | None:
    return await session.scalar(
        select(Agent).where(
            Agent.organization_id == organization_id, Agent.role_key == role_key, Agent.is_active.is_(True)
        )
    )


async def preferences(session: AsyncSession, organization_id: uuid.UUID, agent_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(
        select(OrganizationPreference.content).where(
            OrganizationPreference.organization_id == organization_id,
            OrganizationPreference.is_active.is_(True),
            or_(OrganizationPreference.scope == "organization", OrganizationPreference.agent_id == agent_id),
        )
    )
    return list(rows)


async def set_agent_idle_if_free(session: AsyncSession, agent_id: uuid.UUID | None) -> None:
    if agent_id is None:
        return
    busy = await session.scalar(
        select(func.count(Task.id)).where(
            Task.assigned_agent_id == agent_id, Task.status == TaskStatus.RUNNING
        )
    )
    if not busy:
        await session.execute(update(Agent).where(Agent.id == agent_id).values(status=AgentStatus.IDLE))


async def fail_task(
    session: AsyncSession,
    task: Task,
    category: ErrorCategory,
    message: str,
    recoverable: bool,
) -> None:
    task.status = TaskStatus.FAILED
    task.error_category = category
    task.error_message = message[:4000]
    task.recoverable = recoverable
    task.completed_at = now()
    agent = await session.get(Agent, task.assigned_agent_id) if task.assigned_agent_id else None
    session.add(
        InboxItem(
            organization_id=task.organization_id,
            category=InboxCategory.FAILED,
            severity=Severity.HIGH,
            objective_id=task.objective_id,
            department_id=task.department_id,
            agent_id=task.assigned_agent_id,
            task_id=task.id,
            title=f"Task failed: {task.title}",
            summary=message[:500],
            action_required=recoverable,
            link=f"/objectives/{task.objective_id}?task={task.id}",
        )
    )
    await record_activity(
        session,
        organization_id=task.organization_id,
        event_type="task.failed",
        summary=f"{agent.name if agent else 'Agent'} failed '{task.title}': {message[:160]}",
        objective_id=task.objective_id,
        department_id=task.department_id,
        agent_id=task.assigned_agent_id,
        task_id=task.id,
        actor_type=ActorType.AGENT,
        data={"category": category.value},
    )
    await session.flush()
    await set_agent_idle_if_free(session, task.assigned_agent_id)
    await refresh_objective_status(session, task.objective_id)


async def finish_task(session: AsyncSession, task: Task) -> None:
    if task.status == TaskStatus.COMPLETED:
        return
    task.status = TaskStatus.COMPLETED
    task.completed_at = now()
    agent = await session.get(Agent, task.assigned_agent_id) if task.assigned_agent_id else None
    dependents = (
        await session.scalars(
            select(Task)
            .join(TaskDependency, TaskDependency.task_id == Task.id)
            .where(TaskDependency.depends_on_task_id == task.id)
        )
    ).all()
    for dependent in dependents:
        if dependent.assigned_agent_id and dependent.assigned_agent_id != task.assigned_agent_id:
            session.add(
                AgentMessage(
                    organization_id=task.organization_id,
                    objective_id=task.objective_id,
                    task_id=dependent.id,
                    sender_agent_id=task.assigned_agent_id,
                    recipient_agent_id=dependent.assigned_agent_id,
                    kind=MessageKind.HANDOFF,
                    subject=f"Handoff: {task.title}",
                    body=(task.output_summary or "Deliverable completed.")[:2000],
                    reason=f"Input required for '{dependent.title}'",
                )
            )
    await record_activity(
        session,
        organization_id=task.organization_id,
        event_type="task.completed",
        summary=f"{agent.name if agent else 'Agent'} completed {task.title}",
        objective_id=task.objective_id,
        department_id=task.department_id,
        agent_id=task.assigned_agent_id,
        task_id=task.id,
        actor_type=ActorType.AGENT,
    )
    await session.flush()
    await set_agent_idle_if_free(session, task.assigned_agent_id)
    await refresh_objective_status(session, task.objective_id)
