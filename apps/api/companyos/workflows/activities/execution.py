"""Task execution activities."""

import uuid

from sqlalchemy import select, update
from temporalio import activity

from companyos.agents.prompts import DependencyOutput, agent_system_prompt, task_prompt
from companyos.agents.runtime import AgentRunInput, run_agent
from companyos.db import tenant_scope
from companyos.events import record_activity
from companyos.models import (
    Agent,
    Artifact,
    Objective,
    Organization,
    OrganizationSettings,
    Task,
    TaskDependency,
    TaskRun,
)
from companyos.models.enums import (
    ActorType,
    AgentStatus,
    ErrorCategory,
    ObjectiveStatus,
    ReviewStatus,
    TaskStatus,
)
from companyos.observability import logger
from companyos.providers.llm import LLMError
from companyos.services import artifacts as artifact_service
from companyos.services.integrations import resolve_ai
from companyos.services.usage import BudgetExceeded
from companyos.workflows.activities.shared import (
    MAX_ATTEMPTS,
    fail_task,
    finish_task,
    ids,
    model_for,
    now,
    preferences,
    set_agent_idle_if_free,
)
from companyos.workflows.types import (
    ExecuteResult,
    TaskFailure,
    TaskRef,
)


@activity.defn(name="execute_task")
async def execute_task(ref: TaskRef) -> ExecuteResult:
    organization_id, objective_id, task_id = ids(ref.organization_id, ref.objective_id, ref.task_id)
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
            await fail_task(
                session, task, ErrorCategory.VALIDATION, "No active agent assigned", recoverable=True
            )
            return ExecuteResult(status="failed")
        organization = await session.get(Organization, organization_id)
        settings = await session.scalar(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
        )
        assert organization is not None
        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or now()
        task.retry_count = attempt - 1
        agent.status = AgentStatus.WORKING
        task_run = TaskRun(
            organization_id=organization_id,
            task_id=task.id,
            agent_id=agent.id,
            attempt=attempt,
            kind="revision" if task.revision_count else "execute",
            started_at=now(),
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
                agent, organization.name, await preferences(session, organization_id, agent.id)
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
        task_run_row.finished_at = now()
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
        await set_agent_idle_if_free(session, task.assigned_agent_id)
        return ExecuteResult(
            status="completed", approval_ids=result.approval_ids, requires_review=task.requires_review
        )


async def _record_run_error(organization_id: uuid.UUID, task_run_id: uuid.UUID, message: str) -> None:
    async with tenant_scope(organization_id) as session:
        await session.execute(
            update(TaskRun)
            .where(TaskRun.id == task_run_id)
            .values(status="failed", error=message[:4000], finished_at=now())
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
        await fail_task(session, task, category, message, recoverable)
    return ExecuteResult(status="failed")


@activity.defn(name="mark_task_failed")
async def mark_task_failed(failure: TaskFailure) -> None:
    organization_id, task_id = ids(failure.organization_id, failure.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        if task is not None and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            await fail_task(session, task, ErrorCategory.INTERNAL, failure.message, recoverable=True)


@activity.defn(name="complete_task")
async def complete_task(ref: TaskRef) -> None:
    organization_id, task_id = ids(ref.organization_id, ref.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        await finish_task(session, task)
