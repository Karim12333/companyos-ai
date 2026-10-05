import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from companyos.api.deps import Org, OrgSession
from companyos.api.schemas import (
    ActivityOut,
    AgentOut,
    ArtifactOut,
    DocumentOut,
    ObjectiveOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    TaskOut,
)
from companyos.events import record_activity
from companyos.models import ActivityEvent, Agent, Artifact, Document, Objective, Project, Task
from companyos.models.enums import ActorType, TaskStatus
from companyos.rbac import Permission

router = APIRouter(prefix="/orgs/{org_id}/projects", tags=["projects"])


async def _load(session: OrgSession, org: Org, project_id: uuid.UUID) -> Project:
    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.organization_id == org.organization_id)
    )
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.get("")
async def list_projects(org: Org, session: OrgSession) -> list[dict[str, Any]]:
    projects = (
        await session.scalars(
            select(Project)
            .where(Project.organization_id == org.organization_id)
            .order_by(Project.created_at.desc())
        )
    ).all()
    objectives = (
        await session.scalars(
            select(Objective).where(
                Objective.organization_id == org.organization_id, Objective.project_id.is_not(None)
            )
        )
    ).all()
    return [
        {
            **ProjectOut.model_validate(project).model_dump(mode="json"),
            "objective_count": sum(1 for o in objectives if o.project_id == project.id),
        }
        for project in projects
    ]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, org: Org, session: OrgSession) -> Project:
    org.require(Permission.MANAGE_PROJECTS)
    project = Project(
        organization_id=org.organization_id, created_by_user_id=org.user.id, **body.model_dump()
    )
    session.add(project)
    await session.flush()
    await record_activity(
        session,
        organization_id=org.organization_id,
        event_type="project.created",
        summary=f"CEO created project {project.name}",
        project_id=project.id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
    )
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, org: Org, session: OrgSession
) -> Project:
    org.require(Permission.MANAGE_PROJECTS)
    project = await _load(session, org, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    return project


@router.get("/{project_id}")
async def get_project(project_id: uuid.UUID, org: Org, session: OrgSession) -> dict[str, Any]:
    project = await _load(session, org, project_id)
    objectives = (
        await session.scalars(
            select(Objective).where(Objective.project_id == project.id).order_by(Objective.created_at.desc())
        )
    ).all()
    objective_ids = [o.id for o in objectives]
    tasks = (
        (await session.scalars(select(Task).where(Task.objective_id.in_(objective_ids)))).all()
        if objective_ids
        else []
    )
    agent_ids = {t.assigned_agent_id for t in tasks if t.assigned_agent_id}
    agents = (await session.scalars(select(Agent).where(Agent.id.in_(agent_ids)))).all() if agent_ids else []
    artifacts = (
        await session.scalars(
            select(Artifact)
            .where(
                Artifact.organization_id == org.organization_id,
                (Artifact.project_id == project.id) | Artifact.objective_id.in_(objective_ids),
            )
            .order_by(Artifact.created_at.desc())
        )
    ).all()
    documents = (await session.scalars(select(Document).where(Document.project_id == project.id))).all()
    activity = (
        await session.scalars(
            select(ActivityEvent)
            .where(
                ActivityEvent.organization_id == org.organization_id,
                (ActivityEvent.project_id == project.id) | ActivityEvent.objective_id.in_(objective_ids),
            )
            .order_by(ActivityEvent.created_at.desc())
            .limit(50)
        )
    ).all()
    decisions = (
        (
            await session.scalars(
                select(ActivityEvent)
                .where(
                    ActivityEvent.organization_id == org.organization_id,
                    ActivityEvent.objective_id.in_(objective_ids),
                    ActivityEvent.event_type.in_(["approval.approved", "approval.rejected"]),
                )
                .order_by(ActivityEvent.created_at.desc())
            )
        ).all()
        if objective_ids
        else []
    )
    return {
        "project": ProjectOut.model_validate(project).model_dump(mode="json"),
        "objectives": [ObjectiveOut.model_validate(o).model_dump(mode="json") for o in objectives],
        "agents": [AgentOut.model_validate(a).model_dump(mode="json") for a in agents],
        "tasks": [TaskOut.model_validate(t).model_dump(mode="json") for t in tasks],
        "artifacts": [ArtifactOut.model_validate(a).model_dump(mode="json") for a in artifacts],
        "documents": [DocumentOut.model_validate(d).model_dump(mode="json") for d in documents],
        "activity": [ActivityOut.model_validate(e).model_dump(mode="json") for e in activity],
        "decisions": [ActivityOut.model_validate(e).model_dump(mode="json") for e in decisions],
        "metrics": {
            "tasks_total": len(tasks),
            "tasks_completed": sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
        },
    }
