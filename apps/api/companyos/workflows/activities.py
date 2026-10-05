import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity
from temporalio.exceptions import ApplicationError

from companyos.agents.planning import PlanningError, RoleOption, create_plan
from companyos.agents.prompts import DependencyOutput, agent_system_prompt, task_prompt
from companyos.agents.reporting import write_report
from companyos.agents.review import review_deliverable
from companyos.agents.runtime import AgentRunInput, run_agent
from companyos.db import tenant_scope
from companyos.events import queue_realtime, record_activity
from companyos.models import (
    Agent,
    AgentMessage,
    Approval,
    Artifact,
    Department,
    InboxItem,
    Objective,
    Organization,
    OrganizationPreference,
    OrganizationSettings,
    Task,
    TaskDependency,
    TaskRun,
    WorkflowRun,
)
from companyos.models.enums import (
    OBJECTIVE_TERMINAL,
    ActorType,
    AgentStatus,
    ApprovalStatus,
    ErrorCategory,
    InboxCategory,
    MessageKind,
    ObjectiveStatus,
    ReviewStatus,
    Severity,
    TaskStatus,
)
from companyos.observability import logger
from companyos.providers.llm import LLMError
from companyos.services import artifacts as artifact_service
from companyos.services.integrations import ResolvedAI, resolve_ai
from companyos.services.notifications import notify_approval_required, notify_objective_finished
from companyos.services.reports import render_report_markdown
from companyos.services.usage import BudgetExceeded, record_usage
from companyos.tools import gateway
from companyos.tools.registry import ToolContext
from companyos.workflows.types import (
    ApprovalCheck,
    ExecuteResult,
    FinalizeInput,
    ObjectiveInput,
    ReadySnapshot,
    ReviewResult,
    TaskFailure,
    TaskRef,
)

MAX_ATTEMPTS = 3
NON_RETRYABLE = "NonRetryableTaskError"
ACTIVE_TASK_STATES = {TaskStatus.RUNNING, TaskStatus.REVIEW, TaskStatus.WAITING_FOR_APPROVAL}


def _now() -> datetime:
    return datetime.now(UTC)


def _ids(*values: str) -> list[uuid.UUID]:
    return [uuid.UUID(value) for value in values]


def model_for(agent: Agent | None, ai: ResolvedAI) -> str:
    if ai.source in ("mock", "override"):
        return ai.default_model
    if agent and agent.model:
        return agent.model
    return ai.premium_model if agent and agent.use_premium_model else ai.default_model


async def _agent_by_role(session: AsyncSession, organization_id: uuid.UUID, role_key: str) -> Agent | None:
    return await session.scalar(
        select(Agent).where(
            Agent.organization_id == organization_id, Agent.role_key == role_key, Agent.is_active.is_(True)
        )
    )


async def _preferences(session: AsyncSession, organization_id: uuid.UUID, agent_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(
        select(OrganizationPreference.content).where(
            OrganizationPreference.organization_id == organization_id,
            OrganizationPreference.is_active.is_(True),
            or_(OrganizationPreference.scope == "organization", OrganizationPreference.agent_id == agent_id),
        )
    )
    return list(rows)


async def _set_agent_idle_if_free(session: AsyncSession, agent_id: uuid.UUID | None) -> None:
    if agent_id is None:
        return
    busy = await session.scalar(
        select(func.count(Task.id)).where(
            Task.assigned_agent_id == agent_id, Task.status == TaskStatus.RUNNING
        )
    )
    if not busy:
        await session.execute(update(Agent).where(Agent.id == agent_id).values(status=AgentStatus.IDLE))


async def _fail_task(
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
    task.completed_at = _now()
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
    await _set_agent_idle_if_free(session, task.assigned_agent_id)


async def _complete_task(session: AsyncSession, task: Task) -> None:
    if task.status == TaskStatus.COMPLETED:
        return
    task.status = TaskStatus.COMPLETED
    task.completed_at = _now()
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
    await _set_agent_idle_if_free(session, task.assigned_agent_id)


# ---------------- lifecycle ----------------


@activity.defn(name="start_objective")
async def start_objective(data: ObjectiveInput) -> None:
    organization_id, objective_id = _ids(data.organization_id, data.objective_id)
    info = activity.info()
    async with tenant_scope(organization_id) as session:
        objective = await session.get(Objective, objective_id)
        if objective is None:
            raise ApplicationError("Objective not found", type=NON_RETRYABLE, non_retryable=True)
        objective.status = ObjectiveStatus.RUNNING if data.resume else ObjectiveStatus.PLANNING
        objective.current_stage = "Resuming" if data.resume else "Planning"
        objective.started_at = objective.started_at or _now()
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
                started_at=_now(),
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


@activity.defn(name="plan_objective")
async def plan_objective(data: ObjectiveInput) -> int:
    organization_id, objective_id = _ids(data.organization_id, data.objective_id)
    async with tenant_scope(organization_id) as session:
        existing = await session.scalar(select(func.count(Task.id)).where(Task.objective_id == objective_id))
        if existing:
            return int(existing)
        objective = await session.get(Objective, objective_id)
        organization = await session.get(Organization, organization_id)
        assert objective is not None and organization is not None
        coordinator = (
            await session.get(Agent, objective.coordinator_agent_id)
            if objective.coordinator_agent_id
            else None
        )
        coordinator = coordinator or await _agent_by_role(session, organization_id, "chief_of_staff")
        if coordinator is None:
            raise ApplicationError(
                "No Chief of Staff agent configured", type=NON_RETRYABLE, non_retryable=True
            )
        agents = (
            await session.scalars(
                select(Agent).where(Agent.organization_id == organization_id, Agent.is_active.is_(True))
            )
        ).all()
        departments = {
            department.id: department.name
            for department in (
                await session.scalars(select(Department).where(Department.organization_id == organization_id))
            ).all()
        }
        roles = [
            RoleOption(
                agent.role_key, agent.title, departments.get(agent.department_id, ""), agent.responsibilities
            )
            for agent in agents
            if not agent.is_coordinator
        ]
        ai = await resolve_ai(session, organization_id)
        system_prompt = agent_system_prompt(
            coordinator, organization.name, await _preferences(session, organization_id, coordinator.id)
        )
        objective_snapshot = (objective.title, objective.instruction, objective.context)
        coordinator_id = coordinator.id
        coordinator.status = AgentStatus.WORKING

    try:
        plan = await create_plan(
            organization_id=organization_id,
            objective_id=objective_id,
            coordinator_agent_id=coordinator_id,
            system_prompt=system_prompt,
            objective_title=objective_snapshot[0],
            instruction=objective_snapshot[1],
            context=objective_snapshot[2],
            roles=roles,
            llm=ai.provider,
            model=model_for(coordinator, ai),
        )
    except PlanningError as error:
        raise ApplicationError(str(error), type=NON_RETRYABLE, non_retryable=True) from error
    except LLMError as error:
        if error.recoverable:
            raise
        raise ApplicationError(str(error), type=NON_RETRYABLE, non_retryable=True) from error

    async with tenant_scope(organization_id) as session:
        objective = await session.get(Objective, objective_id)
        assert objective is not None
        agents_by_role = {
            agent.role_key: agent
            for agent in (
                await session.scalars(select(Agent).where(Agent.organization_id == organization_id))
            ).all()
        }
        created: dict[str, Task] = {}
        for index, planned in enumerate(plan.tasks):
            agent = agents_by_role[planned.role]
            task = Task(
                organization_id=organization_id,
                objective_id=objective_id,
                project_id=objective.project_id,
                assigned_agent_id=agent.id,
                department_id=agent.department_id,
                plan_key=planned.key,
                role_key=planned.role,
                title=planned.title,
                instructions=planned.instructions,
                priority=planned.priority,
                sequence=index,
                expected_output_type=planned.expected_output_type,
                acceptance_criteria=planned.acceptance_criteria,
                requires_review=planned.requires_review,
            )
            session.add(task)
            created[planned.key] = task
        await session.flush()
        for planned in plan.tasks:
            for dependency in planned.depends_on:
                session.add(
                    TaskDependency(
                        organization_id=organization_id,
                        task_id=created[planned.key].id,
                        depends_on_task_id=created[dependency].id,
                    )
                )
            session.add(
                AgentMessage(
                    organization_id=organization_id,
                    objective_id=objective_id,
                    task_id=created[planned.key].id,
                    sender_agent_id=coordinator_id,
                    recipient_agent_id=created[planned.key].assigned_agent_id,
                    kind=MessageKind.DELEGATION,
                    subject=f"Assignment: {planned.title}",
                    body=planned.instructions,
                    reason="Planned by the Chief of Staff",
                )
            )
        objective.status = ObjectiveStatus.RUNNING
        objective.current_stage = "Executing"
        objective.plan_summary = plan.summary
        await session.execute(update(Agent).where(Agent.id == coordinator_id).values(status=AgentStatus.IDLE))
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="objective.planned",
            summary=f"Chief of Staff created a plan with {len(plan.tasks)} tasks",
            objective_id=objective_id,
            agent_id=coordinator_id,
            actor_type=ActorType.AGENT,
        )
        return len(plan.tasks)


@activity.defn(name="get_ready_tasks")
async def get_ready_tasks(data: ObjectiveInput) -> ReadySnapshot:
    organization_id, objective_id = _ids(data.organization_id, data.objective_id)
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
        statuses = {task.status for task in tasks}
        if objective.is_paused:
            objective.status, objective.current_stage = ObjectiveStatus.PAUSED, "Paused"
        elif TaskStatus.WAITING_FOR_APPROVAL in statuses:
            objective.status, objective.current_stage = (
                ObjectiveStatus.WAITING_FOR_APPROVAL,
                "Waiting for CEO approval",
            )
        elif TaskStatus.REVIEW in statuses:
            objective.status, objective.current_stage = ObjectiveStatus.REVIEWING, "Reviewing deliverables"
        else:
            objective.status, objective.current_stage = ObjectiveStatus.RUNNING, "Executing"
        queue_realtime(session, organization_id, "objective", {"objective_id": str(objective_id)})

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


# ---------------- task execution ----------------


@activity.defn(name="execute_task")
async def execute_task(ref: TaskRef) -> ExecuteResult:
    organization_id, objective_id, task_id = _ids(ref.organization_id, ref.objective_id, ref.task_id)
    attempt = activity.info().attempt
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        objective = await session.get(Objective, objective_id)
        assert task is not None and objective is not None
        if objective.status == ObjectiveStatus.CANCELLED or task.status in (
            TaskStatus.CANCELLED,
            TaskStatus.FAILED,
        ):
            return ExecuteResult(status="failed")
        if task.status == TaskStatus.COMPLETED:
            return ExecuteResult(status="completed", requires_review=False)
        agent = await session.get(Agent, task.assigned_agent_id) if task.assigned_agent_id else None
        if agent is None or not agent.is_active:
            await _fail_task(
                session, task, ErrorCategory.VALIDATION, "No active agent assigned", recoverable=True
            )
            return ExecuteResult(status="failed")
        organization = await session.get(Organization, organization_id)
        settings = await session.scalar(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
        )
        assert organization is not None
        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or _now()
        task.retry_count = attempt - 1
        agent.status = AgentStatus.WORKING
        task_run = TaskRun(
            organization_id=organization_id,
            task_id=task.id,
            agent_id=agent.id,
            attempt=attempt,
            kind="revision" if task.revision_count else "execute",
            started_at=_now(),
        )
        session.add(task_run)
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="task.started",
            summary=f"{agent.name} {'revising' if task.revision_count else 'started'} {task.title}",
            objective_id=objective_id,
            department_id=task.department_id,
            agent_id=agent.id,
            task_id=task.id,
            actor_type=ActorType.AGENT,
        )
        dependency_tasks = (
            await session.scalars(
                select(Task)
                .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                .where(TaskDependency.task_id == task.id)
            )
        ).all()
        parent = await session.get(Task, task.parent_task_id) if task.parent_task_id else None
        dependency_outputs = [
            DependencyOutput(
                title=dependency.title,
                role=dependency.role_key,
                summary=dependency.output_summary,
                artifact_ids=list((dependency.result or {}).get("artifact_ids", [])),
            )
            for dependency in [*dependency_tasks, *([parent] if parent else [])]
        ]
        ai = await resolve_ai(session, organization_id)
        await session.flush()
        run_input = AgentRunInput(
            organization_id=organization_id,
            agent_id=agent.id,
            agent_role_key=agent.role_key,
            objective_id=objective_id,
            task_id=task.id,
            task_run_id=task_run.id,
            system_prompt=agent_system_prompt(
                agent, organization.name, await _preferences(session, organization_id, agent.id)
            ),
            user_prompt=task_prompt(objective, task, dependency_outputs, task.review_feedback),
            tool_keys=[tool.tool_key for tool in agent.tools if tool.enabled],
            llm=ai.provider,
            model=model_for(agent, ai),
            embedding_model=ai.embedding_model,
            temperature=agent.temperature,
            max_iterations=min(agent.max_iterations, settings.max_task_iterations if settings else 8),
            max_messages_per_task=settings.max_messages_per_task if settings else 6,
            hints={
                "role_key": agent.role_key,
                "task_title": task.title,
                "task_instructions": task.instructions,
                "objective_title": objective.title,
                "expected_output_type": task.expected_output_type,
                "revision": task.revision_count,
                "review_feedback": task.review_feedback,
            },
        )
        task_run_id = task_run.id

    try:
        result = await run_agent(run_input)
    except BudgetExceeded as error:
        return await _record_execution_failure(
            organization_id, task_id, task_run_id, ErrorCategory.BUDGET, str(error), False
        )
    except LLMError as error:
        if error.recoverable and attempt < MAX_ATTEMPTS:
            await _record_run_error(organization_id, task_run_id, str(error))
            raise
        return await _record_execution_failure(
            organization_id, task_id, task_run_id, ErrorCategory.PROVIDER, str(error), error.recoverable
        )
    except Exception as error:
        logger.exception("agent_run_failed", task_id=str(task_id))
        if attempt < MAX_ATTEMPTS:
            await _record_run_error(organization_id, task_run_id, repr(error))
            raise
        return await _record_execution_failure(
            organization_id, task_id, task_run_id, ErrorCategory.INTERNAL, repr(error), True
        )

    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        task_run_row = await session.get(TaskRun, task_run_id)
        objective = await session.get(Objective, objective_id)
        assert task is not None and task_run_row is not None and objective is not None
        artifact_ids = list(dict.fromkeys(result.artifact_ids))
        if not artifact_ids and result.final_output.strip():
            # Agent answered without saving: persist the answer so nothing is lost
            artifact, _ = await artifact_service.save_artifact(
                session,
                organization_id=organization_id,
                title=task.title,
                filename=f"{task.plan_key}.md",
                content=f"# {task.title}\n\n{result.final_output}".encode(),
                mime_type="text/markdown",
                kind=task.expected_output_type,
                objective_id=objective_id,
                project_id=task.project_id,
                task_id=task.id,
                agent_id=task.assigned_agent_id,
                generated_by_mock=run_input.llm.is_mock,
            )
            artifact_ids = [str(artifact.id)]
        previous = list((task.result or {}).get("artifact_ids", []))
        task.result = {
            "artifact_ids": list(dict.fromkeys([*previous, *artifact_ids])),
            "approval_ids": result.approval_ids,
            "iterations": result.iterations,
        }
        task.output_summary = result.final_output[:4000]
        if result.hit_iteration_limit:
            task.execution_metadata = {**task.execution_metadata, "iteration_limit_reached": True}
        task_run_row.status = "succeeded"
        task_run_row.finished_at = _now()
        task_run_row.iterations = result.iterations
        task_run_row.trace = result.trace
        await session.execute(
            update(Artifact)
            .where(Artifact.task_id == task.id)
            .values(review_status=ReviewStatus.PENDING if task.requires_review else ReviewStatus.NOT_REQUIRED)
        )
        if objective.status == ObjectiveStatus.CANCELLED:
            return ExecuteResult(status="failed")
        if result.approval_ids:
            task.status = TaskStatus.WAITING_FOR_APPROVAL
        elif task.requires_review:
            task.status = TaskStatus.REVIEW
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="task.submitted",
            summary=f"{run_input.hints['role_key'].replace('_', ' ').title()} submitted {task.title}",
            objective_id=objective_id,
            department_id=task.department_id,
            agent_id=task.assigned_agent_id,
            task_id=task.id,
            actor_type=ActorType.AGENT,
        )
        await session.flush()
        await _set_agent_idle_if_free(session, task.assigned_agent_id)
        return ExecuteResult(
            status="completed", approval_ids=result.approval_ids, requires_review=task.requires_review
        )


async def _record_run_error(organization_id: uuid.UUID, task_run_id: uuid.UUID, message: str) -> None:
    async with tenant_scope(organization_id) as session:
        await session.execute(
            update(TaskRun)
            .where(TaskRun.id == task_run_id)
            .values(status="failed", error=message[:4000], finished_at=_now())
        )


async def _record_execution_failure(
    organization_id: uuid.UUID,
    task_id: uuid.UUID,
    task_run_id: uuid.UUID,
    category: ErrorCategory,
    message: str,
    recoverable: bool,
) -> ExecuteResult:
    await _record_run_error(organization_id, task_run_id, message)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        await _fail_task(session, task, category, message, recoverable)
    return ExecuteResult(status="failed")


@activity.defn(name="mark_task_failed")
async def mark_task_failed(failure: TaskFailure) -> None:
    organization_id, task_id = _ids(failure.organization_id, failure.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        if task is not None and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            await _fail_task(session, task, ErrorCategory.INTERNAL, failure.message, recoverable=True)


@activity.defn(name="complete_task")
async def complete_task(ref: TaskRef) -> None:
    organization_id, task_id = _ids(ref.organization_id, ref.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        await _complete_task(session, task)


@activity.defn(name="review_task")
async def review_task(ref: TaskRef) -> ReviewResult:
    organization_id, objective_id, task_id = _ids(ref.organization_id, ref.objective_id, ref.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        reviewer = await _agent_by_role(session, organization_id, "reviewer")
        if reviewer is None:
            await _complete_task(session, task)
            return ReviewResult(verdict="accept", feedback="No reviewer configured")
        organization = await session.get(Organization, organization_id)
        settings = await session.scalar(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
        )
        assert organization is not None
        task.status = TaskStatus.REVIEW
        artifacts = (await session.scalars(select(Artifact).where(Artifact.task_id == task.id))).all()
        deliverable = "\n\n".join(
            [await artifact_service.read_text(session, artifact) for artifact in artifacts]
        )
        ai = await resolve_ai(session, organization_id)
        system_prompt = agent_system_prompt(
            reviewer, organization.name, await _preferences(session, organization_id, reviewer.id)
        )
        reviewer_id, author_id = reviewer.id, task.assigned_agent_id
        snapshot = (
            task.title,
            task.instructions,
            list(task.acceptance_criteria),
            task.role_key,
            task.revision_count,
        )
        max_revisions = settings.max_review_revisions if settings else 2
        reviewer_model = model_for(reviewer, ai)

    verdict, response = await review_deliverable(
        llm=ai.provider,
        model=reviewer_model,
        system_prompt=system_prompt,
        task_title=snapshot[0],
        instructions=snapshot[1],
        criteria=snapshot[2],
        deliverable=deliverable or "(no deliverable produced)",
        hints={"role_key": snapshot[3], "revision_count": snapshot[4]},
    )

    async with tenant_scope(organization_id) as session:
        await record_usage(
            session,
            organization_id=organization_id,
            response=response,
            purpose="review",
            objective_id=objective_id,
            task_id=task_id,
            agent_id=reviewer_id,
        )
        task = await session.get(Task, task_id)
        reviewer = await session.get(Agent, reviewer_id)
        author = await session.get(Agent, author_id) if author_id else None
        assert task is not None and reviewer is not None
        wants_revision = verdict.verdict == "revise"
        if wants_revision and task.revision_count < max_revisions:
            task.revision_count += 1
            task.review_feedback = verdict.feedback
            await session.execute(
                update(Artifact)
                .where(Artifact.task_id == task.id)
                .values(review_status=ReviewStatus.CHANGES_REQUESTED)
            )
            session.add(
                AgentMessage(
                    organization_id=organization_id,
                    objective_id=objective_id,
                    task_id=task.id,
                    sender_agent_id=reviewer.id,
                    recipient_agent_id=author_id,
                    kind=MessageKind.FEEDBACK,
                    subject=f"Revision requested: {task.title}",
                    body=verdict.feedback,
                    reason="; ".join(verdict.issues)[:500],
                )
            )
            await record_activity(
                session,
                organization_id=organization_id,
                event_type="review.revision_requested",
                summary=f"Reviewer requested revision on {task.title}",
                objective_id=objective_id,
                agent_id=reviewer.id,
                task_id=task.id,
                actor_type=ActorType.AGENT,
                data={"feedback": verdict.feedback, "score": verdict.score},
            )
            return ReviewResult(verdict="revise", feedback=verdict.feedback)

        task.execution_metadata = {
            **task.execution_metadata,
            "review_score": verdict.score,
            **({"accepted_after_max_revisions": True} if wants_revision else {}),
        }
        await session.execute(
            update(Artifact).where(Artifact.task_id == task.id).values(review_status=ReviewStatus.ACCEPTED)
        )
        session.add(
            AgentMessage(
                organization_id=organization_id,
                objective_id=objective_id,
                task_id=task.id,
                sender_agent_id=reviewer.id,
                recipient_agent_id=author_id,
                kind=MessageKind.FEEDBACK,
                subject=f"Approved: {task.title}",
                body=verdict.feedback or "Meets the acceptance criteria.",
                reason=f"Review score {verdict.score}/10",
            )
        )
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="review.accepted",
            summary=f"Reviewer approved {task.title}" + (f" by {author.name}" if author else ""),
            objective_id=objective_id,
            agent_id=reviewer.id,
            task_id=task.id,
            actor_type=ActorType.AGENT,
            data={"score": verdict.score},
        )
        await _complete_task(session, task)
        return ReviewResult(verdict="accept", feedback=verdict.feedback)


# ---------------- approvals ----------------


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
    organization_id, objective_id, task_id = _ids(ref.organization_id, ref.objective_id, ref.task_id)
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


# ---------------- finalize & notify ----------------


@activity.defn(name="finalize_objective")
async def finalize_objective(data: FinalizeInput) -> str:
    organization_id, objective_id = _ids(data.organization_id, data.objective_id)
    async with tenant_scope(organization_id) as session:
        objective = await session.get(Objective, objective_id)
        assert objective is not None
        if objective.status in OBJECTIVE_TERMINAL and objective.executive_summary:
            return objective.status.value
        tasks = (await session.scalars(select(Task).where(Task.objective_id == objective_id))).all()
        if data.cancelled:
            for task in tasks:
                if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    task.status = TaskStatus.CANCELLED
            await session.execute(
                update(Approval)
                .where(Approval.objective_id == objective_id, Approval.status == ApprovalStatus.PENDING)
                .values(status=ApprovalStatus.CANCELLED)
            )
            await session.execute(
                update(InboxItem)
                .where(InboxItem.objective_id == objective_id, InboxItem.action_required.is_(True))
                .values(action_required=False, resolved_at=_now())
            )
            status = ObjectiveStatus.CANCELLED
        elif data.planning_error:
            status = ObjectiveStatus.FAILED
            objective.issues = [
                *objective.issues,
                {"type": "planning", "message": data.planning_error[:1000]},
            ]
        else:
            for task in tasks:
                if task.status not in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.BLOCKED,
                ):
                    task.status = TaskStatus.BLOCKED
                    task.error_message = task.error_message or "Never became runnable"
            failed = [t for t in tasks if t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)]
            completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
            if not failed:
                status = ObjectiveStatus.COMPLETED
            else:
                status = ObjectiveStatus.COMPLETED_WITH_ISSUES if completed else ObjectiveStatus.FAILED
        stats = await _objective_stats(session, objective, tasks, status)
        reporter = await _agent_by_role(session, organization_id, "executive_reporter")
        organization = await session.get(Organization, organization_id)
        assert organization is not None
        ai = await resolve_ai(session, organization_id)
        deliverables = []
        for artifact in (
            await session.scalars(select(Artifact).where(Artifact.objective_id == objective_id))
        ).all():
            deliverables.append(
                f"## {artifact.title}\n{(await artifact_service.read_text(session, artifact))[:2500]}"
            )
        system_prompt = (
            agent_system_prompt(reporter, organization.name, [])
            if reporter
            else "You write executive reports."
        )
        reporter_id = reporter.id if reporter else None
        reporter_model = model_for(reporter, ai)

    narrative_payload: dict[str, Any]
    try:
        narrative, response = await write_report(
            llm=ai.provider,
            model=reporter_model,
            system_prompt=system_prompt,
            stats=stats,
            deliverables="\n\n".join(deliverables),
        )
        narrative_payload = narrative.model_dump()
    except (LLMError, BudgetExceeded) as error:
        response = None
        narrative_payload = {
            "headline": f"{stats['objective_title']} — {status.value}",
            "overall_assessment": f"Narrative unavailable ({error}). The facts below are authoritative.",
            "key_findings": [],
            "recommendation": "Review deliverables directly.",
            "next_actions": [],
            "risks": [],
        }

    async with tenant_scope(organization_id) as session:
        if response is not None:
            await record_usage(
                session,
                organization_id=organization_id,
                response=response,
                purpose="report",
                objective_id=objective_id,
                agent_id=reporter_id,
            )
        objective = await session.get(Objective, objective_id)
        assert objective is not None
        summary = {**stats, "narrative": narrative_payload}
        objective.status = status
        objective.executive_summary = summary
        objective.completed_at = _now()
        objective.current_stage = status.value.replace("_", " ").title()
        if status == ObjectiveStatus.COMPLETED:
            objective.progress = 100
        artifact, _ = await artifact_service.save_artifact(
            session,
            organization_id=organization_id,
            title=f"Executive Report — {objective.title}",
            filename="executive-report.md",
            content=render_report_markdown(summary).encode(),
            mime_type="text/markdown",
            kind="executive_report",
            objective_id=objective_id,
            project_id=objective.project_id,
            agent_id=reporter_id,
            generated_by_mock=ai.provider.is_mock,
        )
        artifact.review_status = ReviewStatus.NOT_REQUIRED
        # New dict so SQLAlchemy detects the JSONB change
        objective.executive_summary = {**summary, "report_artifact_id": str(artifact.id)}
        failed_like = status in (ObjectiveStatus.FAILED, ObjectiveStatus.COMPLETED_WITH_ISSUES)
        session.add(
            InboxItem(
                organization_id=organization_id,
                category=InboxCategory.FAILED
                if status == ObjectiveStatus.FAILED
                else InboxCategory.COMPLETED,
                severity=Severity.HIGH if failed_like else Severity.INFO,
                objective_id=objective_id,
                agent_id=reporter_id,
                artifact_id=artifact.id,
                title=f"{objective.title} — {status.value.replace('_', ' ').title()}",
                summary=narrative_payload.get("recommendation", ""),
                action_required=False,
                link=f"/objectives/{objective_id}?tab=report",
            )
        )
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="objective.finished",
            summary=f"Executive Reporter delivered the report: {objective.title} ({status.value})",
            objective_id=objective_id,
            agent_id=reporter_id,
            actor_type=ActorType.AGENT,
        )
        await session.execute(
            update(WorkflowRun)
            .where(WorkflowRun.objective_id == objective_id, WorkflowRun.finished_at.is_(None))
            .values(status=status.value.lower(), finished_at=_now())
        )
        await session.execute(
            update(Agent).where(Agent.organization_id == organization_id).values(status=AgentStatus.IDLE)
        )
        return status.value


async def _objective_stats(
    session: AsyncSession, objective: Objective, tasks: Any, status: ObjectiveStatus
) -> dict[str, Any]:
    agent_ids = {task.assigned_agent_id for task in tasks if task.assigned_agent_id}
    agents = (await session.scalars(select(Agent).where(Agent.id.in_(agent_ids)))).all() if agent_ids else []
    departments = (
        (
            await session.scalars(
                select(Department.name).where(Department.id.in_({a.department_id for a in agents}))
            )
        ).all()
        if agents
        else []
    )
    approvals = (await session.scalars(select(Approval).where(Approval.objective_id == objective.id))).all()
    artifact_count = await session.scalar(
        select(func.count(Artifact.id)).where(Artifact.objective_id == objective.id)
    )
    started = objective.started_at or objective.created_at
    revisions = sum(task.revision_count for task in tasks)
    return {
        "objective_title": objective.title,
        "status": status.value,
        "duration_seconds": int((_now() - started).total_seconds()),
        "departments": sorted(departments),
        "agents_involved": len(agent_ids),
        "agent_names": sorted(agent.name for agent in agents),
        "tasks_total": len(tasks),
        "tasks_completed": sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
        "tasks_failed": sum(1 for t in tasks if t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)),
        "completed_titles": [t.title for t in tasks if t.status == TaskStatus.COMPLETED],
        "failed_titles": [t.title for t in tasks if t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)],
        "failures": [
            {
                "task": t.title,
                "category": t.error_category.value if t.error_category else None,
                "message": (t.error_message or "")[:300],
                "recoverable": t.recoverable,
            }
            for t in tasks
            if t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)
        ],
        "revisions_requested": revisions,
        "issues_resolved": revisions,
        "artifacts_created": int(artifact_count or 0),
        "approvals_total": len(approvals),
        "approvals_pending": sum(1 for a in approvals if a.status == ApprovalStatus.PENDING),
        "approvals_approved": sum(1 for a in approvals if a.status == ApprovalStatus.APPROVED),
        "approvals_rejected": sum(1 for a in approvals if a.status == ApprovalStatus.REJECTED),
        "cost_usd": float(objective.cost_usd or 0),
    }


@activity.defn(name="notify_objective_outcome")
async def notify_objective_outcome(data: ObjectiveInput) -> None:
    organization_id, objective_id = _ids(data.organization_id, data.objective_id)
    async with tenant_scope(organization_id) as session:
        await notify_objective_finished(session, organization_id, objective_id)


ALL_ACTIVITIES: list[Callable[..., Any]] = [
    start_objective,
    plan_objective,
    get_ready_tasks,
    execute_task,
    mark_task_failed,
    complete_task,
    review_task,
    notify_approvals,
    decided_approvals,
    resolve_task_approvals,
    finalize_objective,
    notify_objective_outcome,
]
