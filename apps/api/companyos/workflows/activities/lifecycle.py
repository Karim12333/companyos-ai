"""Objective start and DAG scheduling activities."""

import uuid

from sqlalchemy import select
from temporalio import activity
from temporalio.exceptions import ApplicationError

from companyos.db import tenant_scope
from companyos.events import record_activity
from companyos.models import (
    Objective,
    OrganizationSettings,
    Task,
    TaskDependency,
    WorkflowRun,
)
from companyos.models.enums import (
    ErrorCategory,
    ObjectiveStatus,
    TaskStatus,
)
from companyos.services.objective_status import refresh_objective_status
from companyos.services.objectives import ObjectiveStateError, reset_task_for_retry
from companyos.workflows.activities.shared import (
    NON_RETRYABLE,
    ids,
    now,
)
from companyos.workflows.types import (
    ObjectiveInput,
    ReadySnapshot,
    TaskRef,
)


@activity.defn(name="start_objective")
async def start_objective(data: ObjectiveInput) -> None:
    organization_id, objective_id = ids(data.organization_id, data.objective_id)
    info = activity.info()
    async with tenant_scope(organization_id) as session:
        objective = await session.get(Objective, objective_id)
        if objective is None:
            raise ApplicationError("Objective not found", type=NON_RETRYABLE, non_retryable=True)
        objective.status = ObjectiveStatus.RUNNING if data.resume else ObjectiveStatus.PLANNING
        objective.current_stage = "Resuming" if data.resume else "Planning"
        objective.started_at = objective.started_at or now()
        objective.completed_at = None
        objective.is_paused = False
        objective.workflow_id = info.workflow_id
        if data.resume:
            objective.executive_summary = None
        session.add(
            WorkflowRun(
                organization_id=organization_id,
                objective_id=objective_id,
                workflow_id=info.workflow_id,
                run_id=info.workflow_run_id,
                started_at=now(),
            )
        )
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="objective.resumed" if data.resume else "objective.started",
            summary=f"{'Resumed' if data.resume else 'Started'} objective: {objective.title}",
            objective_id=objective_id,
            agent_id=objective.coordinator_agent_id,
        )


@activity.defn(name="get_ready_tasks")
async def get_ready_tasks(data: ObjectiveInput) -> ReadySnapshot:
    organization_id, objective_id = ids(data.organization_id, data.objective_id)
    async with tenant_scope(organization_id) as session:
        tasks = (await session.scalars(select(Task).where(Task.objective_id == objective_id))).all()
        by_id = {task.id: task for task in tasks}
        edges = (
            await session.execute(
                select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
                    TaskDependency.task_id.in_(by_id.keys())
                )
            )
        ).all()
        dependencies: dict[uuid.UUID, list[uuid.UUID]] = {task.id: [] for task in tasks}
        for task_id, depends_on in edges:
            dependencies[task_id].append(depends_on)

        # Cascade: anything waiting on a failed/cancelled/blocked task can never run
        changed = True
        while changed:
            changed = False
            for task in tasks:
                if task.status not in (TaskStatus.QUEUED, TaskStatus.READY):
                    continue
                broken = [
                    by_id[d]
                    for d in dependencies[task.id]
                    if by_id[d].status in (TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED)
                ]
                if broken:
                    task.status = TaskStatus.BLOCKED
                    task.error_category = ErrorCategory.DEPENDENCY
                    task.error_message = f"Blocked because '{broken[0].title}' did not complete"
                    task.recoverable = True
                    changed = True

        ready = [
            task
            for task in tasks
            if task.status in (TaskStatus.QUEUED, TaskStatus.READY)
            and all(by_id[d].status == TaskStatus.COMPLETED for d in dependencies[task.id])
        ]
        for task in ready:
            task.status = TaskStatus.READY
        ready.sort(
            key=lambda task: (["urgent", "high", "normal", "low"].index(task.priority.value), task.sequence)
        )

        objective = await session.get(Objective, objective_id)
        assert objective is not None
        total = len(tasks) or 1
        done = sum(1 for task in tasks if task.status == TaskStatus.COMPLETED)
        objective.progress = int(done * 100 / total)
        if objective.status == ObjectiveStatus.CANCELLED:
            # Invariant: a cancelled objective never starts new work
            ready = []
        await refresh_objective_status(session, objective_id)

        settings = await session.scalar(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
        )
        return ReadySnapshot(
            ready_task_ids=[str(task.id) for task in ready],
            remaining=sum(
                1
                for task in tasks
                if task.status
                not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED)
            ),
            max_parallel=settings.max_parallel_tasks if settings else 4,
            max_review_rounds=settings.max_review_revisions if settings else 2,
        )


@activity.defn(name="requeue_task")
async def requeue_task(ref: TaskRef) -> bool:
    """Requeues a failed task and everything blocked behind it; no-op if it is no longer retryable."""
    organization_id, objective_id, task_id = ids(ref.organization_id, ref.objective_id, ref.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        if task is None or task.objective_id != objective_id:
            return False
        try:
            reset = await reset_task_for_retry(session, task)
        except ObjectiveStateError:
            return False
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="task.requeued",
            summary=f"Requeued {task.title} ({len(reset)} task(s)) for retry",
            objective_id=objective_id,
            task_id=task.id,
        )
        return True
