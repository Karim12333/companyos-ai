import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.api.deps import Org, OrgSession, rate_limit
from companyos.api.schemas import (
    ActivityOut,
    ApprovalOut,
    ArtifactOut,
    EscalationOut,
    MessageOut,
    ObjectiveCreate,
    ObjectiveDetailOut,
    ObjectiveOut,
    TaskOut,
)
from companyos.events import record_activity, record_audit
from companyos.models import (
    ActivityEvent,
    AgentMessage,
    Approval,
    Artifact,
    Escalation,
    Evidence,
    Objective,
    Project,
    Task,
    TaskDependency,
    WorkflowRun,
)
from companyos.models.enums import OBJECTIVE_TERMINAL, ActorType, ObjectiveStatus, TaskStatus
from companyos.rbac import Permission
from companyos.services import objectives as objective_service

router = APIRouter(prefix="/orgs/{org_id}/objectives", tags=["objectives"])
RETRYABLE = (TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED)


async def _load(session: AsyncSession, org: Org, objective_id: uuid.UUID) -> Objective:
    objective = await session.scalar(
        select(Objective).where(
            Objective.id == objective_id, Objective.organization_id == org.organization_id
        )
    )
    if objective is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Objective not found")
    return objective


@router.get("", response_model=list[ObjectiveOut])
async def list_objectives(
    org: Org,
    session: OrgSession,
    status_filter: str | None = Query(default=None, alias="status"),
    project_id: uuid.UUID | None = None,
) -> list[Objective]:
    query = select(Objective).where(Objective.organization_id == org.organization_id)
    if status_filter == "active":
        query = query.where(Objective.status.not_in([*OBJECTIVE_TERMINAL, ObjectiveStatus.DRAFT]))
    elif status_filter:
        query = query.where(Objective.status == status_filter)
    if project_id:
        query = query.where(Objective.project_id == project_id)
    return list((await session.scalars(query.order_by(Objective.created_at.desc()).limit(200))).all())


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_objective(body: ObjectiveCreate, org: Org, session: OrgSession) -> dict[str, Any]:
    org.require(Permission.CREATE_OBJECTIVE)
    await rate_limit(f"objective:{org.organization_id}", 20)
    if body.project_id and not await session.scalar(
        select(Project.id).where(
            Project.id == body.project_id, Project.organization_id == org.organization_id
        )
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown project")
    objective = await objective_service.create_objective(
        session,
        organization_id=org.organization_id,
        user_id=org.user.id,
        title=body.title,
        instruction=body.instruction,
        context=body.context,
        priority=body.priority,
        project_id=body.project_id,
        target_date=body.target_date,
        budget_usd=float(body.budget_usd) if body.budget_usd is not None else None,
        external_actions=body.external_actions,
        acceptance_criteria=[item.strip()[:300] for item in body.success_criteria if item.strip()],
    )
    objective_id = objective.id
    await session.commit()
    workflow_error = None
    try:
        await objective_service.start_workflow(org.organization_id, objective_id)
    except objective_service.WorkflowUnavailable as error:
        workflow_error = str(error)
    await session.refresh(objective)
    return {
        "objective": ObjectiveOut.model_validate(objective).model_dump(mode="json"),
        "workflow_error": workflow_error,
    }


@router.get("/{objective_id}")
async def get_objective(objective_id: uuid.UUID, org: Org, session: OrgSession) -> dict[str, Any]:
    objective = await _load(session, org, objective_id)
    tasks = (
        await session.scalars(
            select(Task).where(Task.objective_id == objective.id).order_by(Task.sequence, Task.created_at)
        )
    ).all()
    edges = (
        await session.execute(
            select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
                TaskDependency.organization_id == org.organization_id,
                TaskDependency.task_id.in_([task.id for task in tasks]),
            )
        )
    ).all()
    depends: dict[uuid.UUID, list[uuid.UUID]] = {}
    for task_id, depends_on in edges:
        depends.setdefault(task_id, []).append(depends_on)
    task_payload = []
    for task in tasks:
        item = TaskOut.model_validate(task)
        item.depends_on = depends.get(task.id, [])
        task_payload.append(item.model_dump(mode="json"))
    messages = (
        await session.scalars(
            select(AgentMessage)
            .where(AgentMessage.objective_id == objective.id)
            .order_by(AgentMessage.created_at)
        )
    ).all()
    approvals = (
        await session.scalars(
            select(Approval).where(Approval.objective_id == objective.id).order_by(Approval.created_at.desc())
        )
    ).all()
    artifacts = (
        await session.scalars(
            select(Artifact).where(Artifact.objective_id == objective.id).order_by(Artifact.created_at)
        )
    ).all()
    activity = (
        await session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.objective_id == objective.id)
            .order_by(ActivityEvent.created_at.desc())
            .limit(200)
        )
    ).all()
    evidence = (
        await session.scalars(
            select(Evidence).where(Evidence.objective_id == objective.id).order_by(Evidence.created_at)
        )
    ).all()
    escalations = (
        await session.scalars(
            select(Escalation)
            .where(Escalation.objective_id == objective.id)
            .order_by(Escalation.created_at.desc())
        )
    ).all()
    runs = (
        await session.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.objective_id == objective.id)
            .order_by(WorkflowRun.created_at)
        )
    ).all()
    return {
        "objective": ObjectiveDetailOut.model_validate(objective).model_dump(mode="json"),
        "tasks": task_payload,
        "messages": [MessageOut.model_validate(item).model_dump(mode="json") for item in messages],
        "approvals": [ApprovalOut.model_validate(item).model_dump(mode="json") for item in approvals],
        "artifacts": [ArtifactOut.model_validate(item).model_dump(mode="json") for item in artifacts],
        "evidence": [
            {
                "id": item.id,
                "ref": item.ref,
                "kind": item.kind,
                "claim": item.claim,
                "source_url": item.source_url,
                "source_title": item.source_title,
                "excerpt": item.excerpt,
                "confidence": item.confidence,
                "task_id": item.task_id,
                "agent_id": item.agent_id,
                "collected_at": item.collected_at,
            }
            for item in evidence
        ],
        "escalations": [EscalationOut.model_validate(item).model_dump(mode="json") for item in escalations],
        "activity": [ActivityOut.model_validate(item).model_dump(mode="json") for item in activity],
        "workflow_runs": [
            {
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
            for run in runs
        ],
    }


@router.post("/{objective_id}/start", response_model=ObjectiveOut)
async def start_objective(objective_id: uuid.UUID, org: Org, session: OrgSession) -> Objective:
    org.require(Permission.CONTROL_OBJECTIVE)
    objective = await _load(session, org, objective_id)
    if objective.status != ObjectiveStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only draft objectives can be started")
    try:
        await objective_service.start_workflow(org.organization_id, objective.id)
    except objective_service.WorkflowUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    await session.refresh(objective)
    return objective


@router.post("/{objective_id}/pause", response_model=ObjectiveOut)
async def pause_objective(objective_id: uuid.UUID, org: Org, session: OrgSession) -> Objective:
    return await _set_paused(objective_id, org, session, True)


@router.post("/{objective_id}/resume", response_model=ObjectiveOut)
async def resume_objective(objective_id: uuid.UUID, org: Org, session: OrgSession) -> Objective:
    return await _set_paused(objective_id, org, session, False)


async def _set_paused(objective_id: uuid.UUID, org: Org, session: AsyncSession, paused: bool) -> Objective:
    org.require(Permission.CONTROL_OBJECTIVE)
    objective = await _load(session, org, objective_id)
    try:
        await objective_service.set_paused(session, objective, paused, org.user.id)
    except objective_service.ObjectiveStateError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    await session.commit()
    await objective_service.signal_workflow(objective.workflow_id, "pause" if paused else "resume")
    return objective


@router.post("/{objective_id}/cancel", response_model=ObjectiveOut)
async def cancel_objective(objective_id: uuid.UUID, org: Org, session: OrgSession) -> Objective:
    org.require(Permission.CONTROL_OBJECTIVE)
    objective = await _load(session, org, objective_id)
    if objective.status in OBJECTIVE_TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, "Objective already finished")
    await record_activity(
        session,
        organization_id=org.organization_id,
        event_type="objective.cancel_requested",
        summary=f"CEO cancelled {objective.title}",
        objective_id=objective.id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
    )
    await record_audit(
        session,
        action="objective.cancel",
        organization_id=org.organization_id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
        target_type="objective",
        target_id=objective.id,
    )
    signalled = await objective_service.signal_workflow(objective.workflow_id, "cancel")
    if not signalled:
        objective.status = ObjectiveStatus.CANCELLED
        objective.current_stage = "Cancelled"
    return objective


@router.post("/{objective_id}/tasks/{task_id}/retry", response_model=ObjectiveOut)
async def retry_task(objective_id: uuid.UUID, task_id: uuid.UUID, org: Org, session: OrgSession) -> Objective:
    org.require(Permission.CONTROL_OBJECTIVE)
    objective = await _load(session, org, objective_id)
    task = await session.scalar(
        select(Task).where(
            Task.id == task_id, Task.objective_id == objective.id, Task.organization_id == org.organization_id
        )
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if task.status not in RETRYABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only failed, blocked or cancelled tasks can be retried"
        )
    await record_activity(
        session,
        organization_id=org.organization_id,
        event_type="task.retry_requested",
        summary=f"CEO retried {task.title}",
        objective_id=objective.id,
        task_id=task.id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
    )
    await session.commit()
    # A live run (even one that is finishing) requeues the task itself: never two runs per objective
    if not await objective_service.signal_workflow(objective.workflow_id, "retry_task", str(task.id)):
        await objective_service.reset_task_for_retry(session, task)
        await session.commit()
        try:
            await objective_service.start_workflow(org.organization_id, objective.id, resume=True)
        except objective_service.WorkflowUnavailable as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    await session.refresh(objective)
    return objective
