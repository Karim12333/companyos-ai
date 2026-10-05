import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError

from companyos.config import get_settings
from companyos.db import tenant_scope
from companyos.events import record_activity, record_audit
from companyos.models import Agent, Objective, Task, TaskDependency, WorkflowRun
from companyos.models.enums import (
    OBJECTIVE_TERMINAL,
    ActorType,
    ErrorCategory,
    ObjectiveStatus,
    Priority,
    TaskStatus,
)
from companyos.observability import logger
from companyos.workflows.client import get_temporal_client
from companyos.workflows.types import ObjectiveInput


class WorkflowUnavailable(Exception):
    pass


class ObjectiveStateError(Exception):
    pass


async def create_objective(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    instruction: str,
    context: str = "",
    priority: Priority = Priority.NORMAL,
    project_id: uuid.UUID | None = None,
    target_date: datetime | None = None,
    budget_usd: float | None = None,
    external_actions: str | None = None,
) -> Objective:
    coordinator = await session.scalar(
        select(Agent).where(
            Agent.organization_id == organization_id,
            Agent.is_coordinator.is_(True),
            Agent.is_active.is_(True),
        )
    )
    objective = Objective(
        organization_id=organization_id,
        created_by_user_id=user_id,
        coordinator_agent_id=coordinator.id if coordinator else None,
        project_id=project_id,
        title=title,
        instruction=instruction,
        context=context,
        priority=priority,
        target_date=target_date,
        budget_usd=budget_usd,
        approval_policy={"external_actions": external_actions or "require_approval"},
    )
    session.add(objective)
    await session.flush()
    await record_activity(
        session,
        organization_id=organization_id,
        event_type="objective.created",
        summary=f"CEO created objective: {title}",
        objective_id=objective.id,
        project_id=project_id,
        actor_type=ActorType.USER,
        actor_user_id=user_id,
    )
    await record_audit(
        session,
        action="objective.create",
        organization_id=organization_id,
        actor_type=ActorType.USER,
        actor_user_id=user_id,
        target_type="objective",
        target_id=objective.id,
    )
    return objective


async def _run_count(session: AsyncSession, objective_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count(WorkflowRun.id)).where(WorkflowRun.objective_id == objective_id)
        )
        or 0
    )


async def start_workflow(organization_id: uuid.UUID, objective_id: uuid.UUID, resume: bool = False) -> str:
    """Starts the durable workflow after the objective row is committed."""
    async with tenant_scope(organization_id) as session:
        runs = await _run_count(session, objective_id)
    workflow_id = f"objective-{objective_id}" + (f"-r{runs}" if runs else "")
    try:
        client = await get_temporal_client()
        await client.start_workflow(
            "ObjectiveWorkflow",
            ObjectiveInput(str(organization_id), str(objective_id), resume),
            id=workflow_id,
            task_queue=get_settings().temporal_task_queue,
        )
    except (RPCError, OSError, RuntimeError) as error:
        logger.error("workflow_start_failed", objective_id=str(objective_id), error=str(error))
        raise WorkflowUnavailable(
            "The workflow engine is unavailable; the objective was saved as a draft"
        ) from error
    async with tenant_scope(organization_id) as session:
        objective = await session.get(Objective, objective_id)
        if objective is not None:
            objective.workflow_id = workflow_id
            if objective.status == ObjectiveStatus.DRAFT:
                objective.status = ObjectiveStatus.PLANNING
                objective.current_stage = "Queued for planning"
    return workflow_id


async def signal_workflow(workflow_id: str | None, signal: str, *args: str) -> bool:
    if not workflow_id:
        return False
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        description = await handle.describe()
        if description.status != WorkflowExecutionStatus.RUNNING:
            return False
        await handle.signal(signal, *args)
        return True
    except RPCError as error:
        logger.warning("workflow_signal_failed", workflow_id=workflow_id, signal=signal, error=str(error))
        return False


async def set_paused(session: AsyncSession, objective: Objective, paused: bool, user_id: uuid.UUID) -> None:
    if objective.status in OBJECTIVE_TERMINAL:
        raise ObjectiveStateError("Objective already finished")
    objective.is_paused = paused
    objective.status = ObjectiveStatus.PAUSED if paused else ObjectiveStatus.RUNNING
    objective.current_stage = "Paused" if paused else "Executing"
    await record_activity(
        session,
        organization_id=objective.organization_id,
        event_type="objective.paused" if paused else "objective.resumed",
        summary=f"CEO {'paused' if paused else 'resumed'} {objective.title}",
        objective_id=objective.id,
        actor_type=ActorType.USER,
        actor_user_id=user_id,
    )


async def reset_task_for_retry(session: AsyncSession, task: Task) -> list[Task]:
    """Requeues a failed task and everything blocked behind it."""
    if task.status not in (TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED):
        raise ObjectiveStateError("Only failed, blocked or cancelled tasks can be retried")
    reset = [task]
    frontier = [task.id]
    while frontier:
        dependents = (
            await session.scalars(
                select(Task)
                .join(TaskDependency, TaskDependency.task_id == Task.id)
                .where(TaskDependency.depends_on_task_id.in_(frontier))
            )
        ).all()
        frontier = []
        for dependent in dependents:
            if dependent.status in (TaskStatus.BLOCKED, TaskStatus.CANCELLED) and dependent not in reset:
                reset.append(dependent)
                frontier.append(dependent.id)
    for item in reset:
        item.status = TaskStatus.QUEUED
        item.error_category = None
        item.error_message = None
        item.recoverable = None
        item.completed_at = None
        item.retry_count = 0
    return reset


def describe_failure(category: ErrorCategory | None) -> str:
    return (
        {
            ErrorCategory.PROVIDER: "AI provider error",
            ErrorCategory.BUDGET: "Budget limit reached",
            ErrorCategory.DEPENDENCY: "Blocked by a failed dependency",
            ErrorCategory.POLICY: "Denied by policy",
            ErrorCategory.TOOL: "Tool failure",
            ErrorCategory.TIMEOUT: "Timed out",
            ErrorCategory.VALIDATION: "Invalid configuration",
        }.get(category, "Unexpected error")
        if category
        else "Unknown"
    )
