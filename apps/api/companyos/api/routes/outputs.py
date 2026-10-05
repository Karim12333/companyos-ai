import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.api.deps import Org, OrgSession, authorize_stream
from companyos.api.schemas import (
    ActivityOut,
    ApprovalDecision,
    ApprovalOut,
    ArtifactOut,
    ArtifactVersionOut,
    FeedbackCreate,
    FeedbackOut,
    InboxItemOut,
)
from companyos.events import get_redis, org_channel, record_activity
from companyos.models import (
    ActivityEvent,
    AgentFeedback,
    Approval,
    Artifact,
    ArtifactVersion,
    InboxItem,
    Objective,
    Task,
)
from companyos.models.enums import ActorType, ApprovalStatus, ArtifactApprovalStatus
from companyos.rbac import Permission
from companyos.services import artifacts as artifact_service
from companyos.services.approvals import ApprovalStateError, decide_approval, objective_workflow_id
from companyos.services.objectives import signal_workflow

router = APIRouter(prefix="/orgs/{org_id}", tags=["outputs"])
HEARTBEAT_SECONDS = 15


# ---------- artifacts ----------


async def _artifact(session: AsyncSession, org: Org, artifact_id: uuid.UUID) -> Artifact:
    artifact = await session.scalar(
        select(Artifact).where(Artifact.id == artifact_id, Artifact.organization_id == org.organization_id)
    )
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
    return artifact


@router.get("/artifacts", response_model=list[ArtifactOut])
async def list_artifacts(
    org: Org,
    session: OrgSession,
    objective_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    kind: str | None = None,
) -> list[Artifact]:
    query = select(Artifact).where(Artifact.organization_id == org.organization_id)
    if objective_id:
        query = query.where(Artifact.objective_id == objective_id)
    if project_id:
        query = query.where(Artifact.project_id == project_id)
    if agent_id:
        query = query.where(Artifact.agent_id == agent_id)
    if kind:
        query = query.where(Artifact.kind == kind)
    return list((await session.scalars(query.order_by(Artifact.updated_at.desc()).limit(300))).all())


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: uuid.UUID, org: Org, session: OrgSession) -> dict[str, Any]:
    artifact = await _artifact(session, org, artifact_id)
    versions = (
        await session.scalars(
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_id == artifact.id)
            .order_by(ArtifactVersion.version.desc())
        )
    ).all()
    objective = await session.get(Objective, artifact.objective_id) if artifact.objective_id else None
    task = await session.get(Task, artifact.task_id) if artifact.task_id else None
    feedback = (
        await session.scalars(
            select(AgentFeedback)
            .where(AgentFeedback.artifact_id == artifact.id)
            .order_by(AgentFeedback.created_at)
        )
    ).all()
    return {
        "artifact": ArtifactOut.model_validate(artifact).model_dump(mode="json"),
        "versions": [ArtifactVersionOut.model_validate(item).model_dump(mode="json") for item in versions],
        "objective": {"id": objective.id, "title": objective.title} if objective else None,
        "task": {"id": task.id, "title": task.title, "status": task.status.value} if task else None,
        "feedback": [FeedbackOut.model_validate(item).model_dump(mode="json") for item in feedback],
    }


@router.get("/artifacts/{artifact_id}/content")
async def artifact_content(
    artifact_id: uuid.UUID,
    org: Org,
    session: OrgSession,
    version: int | None = None,
    download: bool = False,
) -> Response:
    artifact = await _artifact(session, org, artifact_id)
    try:
        data = await artifact_service.read_bytes(session, artifact, version)
    except LookupError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    is_text = artifact.mime_type.startswith(("text/", "application/json"))
    disposition = "attachment" if download else "inline"
    return Response(
        content=data,
        # Text is always served as plain text so a browser never renders agent output as HTML
        media_type="text/plain; charset=utf-8" if is_text and not download else artifact.mime_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{artifact.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def create_feedback(body: FeedbackCreate, org: Org, session: OrgSession) -> AgentFeedback:
    org.require(Permission.GIVE_FEEDBACK)
    agent_id = body.agent_id
    objective_id = body.objective_id
    if body.artifact_id:
        artifact = await _artifact(session, org, body.artifact_id)
        agent_id = agent_id or artifact.agent_id
        objective_id = objective_id or artifact.objective_id
    feedback = AgentFeedback(
        organization_id=org.organization_id,
        artifact_id=body.artifact_id,
        task_id=body.task_id,
        agent_id=agent_id,
        objective_id=objective_id,
        user_id=org.user.id,
        rating=body.rating,
        comment=body.comment,
    )
    session.add(feedback)
    await record_activity(
        session,
        organization_id=org.organization_id,
        event_type="feedback.created",
        summary=f"CEO gave feedback: {body.comment[:120]}",
        agent_id=agent_id,
        objective_id=objective_id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
    )
    await session.flush()
    return feedback


# ---------- approvals ----------


@router.get("/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    org: Org, session: OrgSession, status_filter: str | None = Query(default=None, alias="status")
) -> list[Approval]:
    query = select(Approval).where(Approval.organization_id == org.organization_id)
    if status_filter:
        query = query.where(Approval.status == status_filter.upper())
    return list((await session.scalars(query.order_by(Approval.created_at.desc()).limit(200))).all())


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: uuid.UUID, org: Org, session: OrgSession) -> dict[str, Any]:
    approval = await session.scalar(
        select(Approval).where(Approval.id == approval_id, Approval.organization_id == org.organization_id)
    )
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
    objective = await session.get(Objective, approval.objective_id) if approval.objective_id else None
    task = await session.get(Task, approval.task_id) if approval.task_id else None
    artifacts = (
        (await session.scalars(select(Artifact).where(Artifact.task_id == approval.task_id))).all()
        if approval.task_id
        else []
    )
    return {
        "approval": ApprovalOut.model_validate(approval).model_dump(mode="json"),
        "objective": {"id": objective.id, "title": objective.title} if objective else None,
        "task": {"id": task.id, "title": task.title, "status": task.status.value} if task else None,
        "artifacts": [ArtifactOut.model_validate(item).model_dump(mode="json") for item in artifacts],
    }


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
async def decide(approval_id: uuid.UUID, body: ApprovalDecision, org: Org, session: OrgSession) -> Approval:
    org.require(Permission.DECIDE_APPROVAL)
    try:
        approval = await decide_approval(
            session,
            organization_id=org.organization_id,
            approval_id=approval_id,
            approve=body.approve,
            user_id=org.user.id,
            note=body.note,
        )
    except LookupError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except ApprovalStateError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    if approval.artifact_id:
        await session.execute(
            update(Artifact)
            .where(Artifact.id == approval.artifact_id)
            .values(
                approval_status=ArtifactApprovalStatus.APPROVED
                if body.approve
                else ArtifactApprovalStatus.REJECTED
            )
        )
    workflow_id = await objective_workflow_id(session, approval)
    await session.commit()
    # The workflow also reconciles with the database periodically if this signal is lost
    await signal_workflow(workflow_id, "approval_decided", str(approval.id))
    return approval


# ---------- inbox ----------


@router.get("/inbox")
async def list_inbox(
    org: Org,
    session: OrgSession,
    category: str | None = None,
    unread: bool = False,
    limit: int = Query(default=100, le=300),
) -> dict[str, Any]:
    query = select(InboxItem).where(InboxItem.organization_id == org.organization_id)
    if category:
        query = query.where(InboxItem.category == category.upper())
    if unread:
        query = query.where(InboxItem.is_read.is_(False))
    items = (await session.scalars(query.order_by(InboxItem.created_at.desc()).limit(limit))).all()
    counts = dict(
        (
            await session.execute(
                select(InboxItem.category, func.count(InboxItem.id))
                .where(InboxItem.organization_id == org.organization_id, InboxItem.is_read.is_(False))
                .group_by(InboxItem.category)
            )
        ).all()
    )
    action_required = await session.scalar(
        select(func.count(InboxItem.id)).where(
            InboxItem.organization_id == org.organization_id, InboxItem.action_required.is_(True)
        )
    )
    return {
        "items": [InboxItemOut.model_validate(item).model_dump(mode="json") for item in items],
        "unread_by_category": {key.value: value for key, value in counts.items()},
        "unread_total": sum(counts.values()),
        "action_required": action_required or 0,
    }


@router.post("/inbox/{item_id}/read", response_model=InboxItemOut)
async def mark_read(item_id: uuid.UUID, org: Org, session: OrgSession) -> InboxItem:
    item = await session.scalar(
        select(InboxItem).where(InboxItem.id == item_id, InboxItem.organization_id == org.organization_id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inbox item not found")
    item.is_read = True
    return item


@router.post("/inbox/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(org: Org, session: OrgSession) -> None:
    await session.execute(
        update(InboxItem)
        .where(
            InboxItem.organization_id == org.organization_id,
            InboxItem.is_read.is_(False),
            InboxItem.action_required.is_(False),
        )
        .values(is_read=True)
    )


# ---------- activity ----------


@router.get("/activity", response_model=list[ActivityOut])
async def list_activity(
    org: Org,
    session: OrgSession,
    objective_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    event_type: str | None = None,
    before: datetime | None = None,
    limit: int = Query(default=100, le=500),
) -> list[ActivityEvent]:
    query = select(ActivityEvent).where(ActivityEvent.organization_id == org.organization_id)
    if objective_id:
        query = query.where(ActivityEvent.objective_id == objective_id)
    if project_id:
        query = query.where(
            (ActivityEvent.project_id == project_id)
            | ActivityEvent.objective_id.in_(select(Objective.id).where(Objective.project_id == project_id))
        )
    if department_id:
        query = query.where(ActivityEvent.department_id == department_id)
    if agent_id:
        query = query.where(ActivityEvent.agent_id == agent_id)
    if event_type:
        query = query.where(ActivityEvent.event_type.startswith(event_type))
    if before:
        query = query.where(ActivityEvent.created_at < before)
    return list((await session.scalars(query.order_by(ActivityEvent.created_at.desc()).limit(limit))).all())


@router.get("/events/stream")
async def event_stream(org_id: uuid.UUID, request: Request) -> StreamingResponse:
    await authorize_stream(request, org_id)
    channel = org_channel(org_id)

    async def generate() -> AsyncIterator[str]:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(channel)
        try:
            yield f"event: ready\ndata: {json.dumps({'at': datetime.now(UTC).isoformat()})}\n\n"
            last_beat = asyncio.get_running_loop().time()
            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    yield f"data: {message['data']}\n\n"
                now = asyncio.get_running_loop().time()
                if now - last_beat > HEARTBEAT_SECONDS:
                    last_beat = now
                    yield ": heartbeat\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/approvals-pending-count")
async def pending_count(org: Org, session: OrgSession) -> dict[str, int]:
    count = await session.scalar(
        select(func.count(Approval.id)).where(
            Approval.organization_id == org.organization_id, Approval.status == ApprovalStatus.PENDING
        )
    )
    return {"pending": count or 0}
