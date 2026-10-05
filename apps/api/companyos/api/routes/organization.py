import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.api.deps import Org, OrgSession
from companyos.api.schemas import (
    ActivityOut,
    AgentCreate,
    AgentDetailOut,
    AgentOut,
    AgentUpdate,
    ApprovalOut,
    ArtifactOut,
    DepartmentCreate,
    DepartmentOut,
    EscalationOut,
    MessageOut,
    ObjectiveOut,
    TaskOut,
)
from companyos.events import record_audit
from companyos.models import (
    ActivityEvent,
    Agent,
    AgentMessage,
    AgentRelationship,
    AgentTool,
    Approval,
    Artifact,
    Department,
    Escalation,
    InboxItem,
    ModelUsage,
    Objective,
    Organization,
    OrganizationSettings,
    Task,
)
from companyos.models.enums import (
    ActorType,
    ApprovalStatus,
    EscalationStatus,
    InboxCategory,
    ObjectiveStatus,
    TaskStatus,
)
from companyos.rbac import Permission
from companyos.services.integrations import get_integration, secret_last4
from companyos.services.organizations import slugify
from companyos.tools.registry import TOOL_REGISTRY

router = APIRouter(prefix="/orgs/{org_id}", tags=["organization"])

ACTIVE_TASK = (TaskStatus.RUNNING, TaskStatus.REVIEW, TaskStatus.WAITING_FOR_APPROVAL)
INACTIVE_OBJECTIVE = (
    ObjectiveStatus.DRAFT,
    ObjectiveStatus.COMPLETED,
    ObjectiveStatus.COMPLETED_WITH_ISSUES,
    ObjectiveStatus.FAILED,
    ObjectiveStatus.CANCELLED,
)


def _start_of_today() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def ai_status(session: AsyncSession, organization_id: uuid.UUID) -> dict[str, Any]:
    integration = await get_integration(session, organization_id, "ai_provider")
    configured = bool(integration and integration.enabled and await secret_last4(session, integration))
    return {
        "configured": configured,
        "provider": "organization" if configured else "mock",
        "default_model": (integration.config or {}).get("default_model")
        if configured and integration
        else None,
    }


@router.get("")
async def get_organization(org: Org, session: OrgSession) -> dict[str, Any]:
    organization = await session.get(Organization, org.organization_id)
    assert organization is not None
    return {
        "id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
        "template_key": organization.template_key,
        "role": org.role.value,
        "ai": await ai_status(session, org.organization_id),
    }


@router.get("/headquarters")
async def headquarters(org: Org, session: OrgSession) -> dict[str, Any]:
    organization_id = org.organization_id
    today = _start_of_today()
    active_objectives = await session.scalar(
        select(func.count(Objective.id)).where(
            Objective.organization_id == organization_id, Objective.status.not_in(INACTIVE_OBJECTIVE)
        )
    )
    agents_working = await session.scalar(
        select(func.count(func.distinct(Task.assigned_agent_id))).where(
            Task.organization_id == organization_id, Task.status == TaskStatus.RUNNING
        )
    )
    tasks_completed_today = await session.scalar(
        select(func.count(Task.id)).where(
            Task.organization_id == organization_id,
            Task.status == TaskStatus.COMPLETED,
            Task.completed_at >= today,
        )
    )
    pending_approvals = (
        await session.scalars(
            select(Approval)
            .where(Approval.organization_id == organization_id, Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at.desc())
        )
    ).all()
    open_escalations = (
        await session.scalars(
            select(Escalation)
            .where(Escalation.organization_id == organization_id, Escalation.status == EscalationStatus.OPEN)
            .order_by(Escalation.created_at.desc())
        )
    ).all()
    failures = (
        await session.scalars(
            select(InboxItem)
            .where(
                InboxItem.organization_id == organization_id,
                InboxItem.category == InboxCategory.FAILED,
                InboxItem.resolved_at.is_(None),
                InboxItem.is_read.is_(False),
            )
            .order_by(InboxItem.created_at.desc())
            .limit(5)
        )
    ).all()
    departments = (
        await session.scalars(
            select(Department)
            .where(Department.organization_id == organization_id)
            .order_by(Department.sort_order)
        )
    ).all()
    agent_counts = dict(
        (
            await session.execute(
                select(Agent.department_id, func.count(Agent.id))
                .where(Agent.organization_id == organization_id, Agent.is_active.is_(True))
                .group_by(Agent.department_id)
            )
        ).all()
    )
    active_counts = dict(
        (
            await session.execute(
                select(Task.department_id, func.count(Task.id))
                .where(Task.organization_id == organization_id, Task.status.in_(ACTIVE_TASK))
                .group_by(Task.department_id)
            )
        ).all()
    )
    completed_today_counts = dict(
        (
            await session.execute(
                select(Task.department_id, func.count(Task.id))
                .where(
                    Task.organization_id == organization_id,
                    Task.status == TaskStatus.COMPLETED,
                    Task.completed_at >= today,
                )
                .group_by(Task.department_id)
            )
        ).all()
    )
    live = (
        await session.execute(
            select(Task, Agent, Objective.title)
            .join(Agent, Agent.id == Task.assigned_agent_id)
            .join(Objective, Objective.id == Task.objective_id)
            .where(Task.organization_id == organization_id, Task.status.in_(ACTIVE_TASK))
            .order_by(Task.started_at.desc().nullslast())
            .limit(12)
        )
    ).all()
    objectives = (
        await session.scalars(
            select(Objective)
            .where(Objective.organization_id == organization_id)
            .order_by(Objective.created_at.desc())
            .limit(6)
        )
    ).all()
    activity = (
        await session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.organization_id == organization_id)
            .order_by(ActivityEvent.created_at.desc())
            .limit(15)
        )
    ).all()
    settings = await session.scalar(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
    )

    def department_status(department_id: uuid.UUID) -> str:
        if active_counts.get(department_id):
            return "active"
        return "completed_today" if completed_today_counts.get(department_id) else "idle"

    return {
        "ceo_name": (settings.ceo_name if settings else None) or org.user.full_name.split(" ")[0],
        "health": {
            "active_objectives": active_objectives or 0,
            "agents_working": agents_working or 0,
            "tasks_completed_today": tasks_completed_today or 0,
            "waiting_for_approval": len(pending_approvals),
            "decisions_required": len(open_escalations),
        },
        "departments": [
            {
                **DepartmentOut.model_validate(department).model_dump(mode="json"),
                "agent_count": agent_counts.get(department.id, 0),
                "active_tasks": active_counts.get(department.id, 0),
                "status": department_status(department.id),
            }
            for department in departments
        ],
        "live": [
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "agent_title": agent.title,
                "task_id": task.id,
                "task_title": task.title,
                "task_status": task.status.value,
                "objective_id": task.objective_id,
                "objective_title": objective_title,
                "started_at": task.started_at,
            }
            for task, agent, objective_title in live
        ],
        "attention": {
            "escalations": [
                EscalationOut.model_validate(item).model_dump(mode="json") for item in open_escalations[:6]
            ],
            "approvals": [
                ApprovalOut.model_validate(item).model_dump(mode="json") for item in pending_approvals[:6]
            ],
            "failures": [
                {
                    "id": item.id,
                    "title": item.title,
                    "summary": item.summary,
                    "link": item.link,
                    "created_at": item.created_at,
                }
                for item in failures
            ],
        },
        "objectives": [ObjectiveOut.model_validate(item).model_dump(mode="json") for item in objectives],
        "activity": [ActivityOut.model_validate(item).model_dump(mode="json") for item in activity],
        "ai": await ai_status(session, organization_id),
    }


# ---------- departments ----------


@router.get("/departments")
async def list_departments(org: Org, session: OrgSession) -> list[dict[str, Any]]:
    departments = (
        await session.scalars(
            select(Department)
            .where(Department.organization_id == org.organization_id)
            .order_by(Department.sort_order)
        )
    ).all()
    agents = (await session.scalars(select(Agent).where(Agent.organization_id == org.organization_id))).all()
    active = dict(
        (
            await session.execute(
                select(Task.department_id, func.count(Task.id))
                .where(Task.organization_id == org.organization_id, Task.status.in_(ACTIVE_TASK))
                .group_by(Task.department_id)
            )
        ).all()
    )
    completed = dict(
        (
            await session.execute(
                select(Task.department_id, func.count(Task.id))
                .where(Task.organization_id == org.organization_id, Task.status == TaskStatus.COMPLETED)
                .group_by(Task.department_id)
            )
        ).all()
    )
    by_id = {agent.id: agent for agent in agents}
    return [
        {
            **DepartmentOut.model_validate(department).model_dump(mode="json"),
            "agent_count": sum(1 for a in agents if a.department_id == department.id and a.is_active),
            "active_tasks": active.get(department.id, 0),
            "completed_tasks": completed.get(department.id, 0),
            "manager_name": by_id[department.manager_agent_id].name
            if department.manager_agent_id in by_id
            else None,
        }
        for department in departments
    ]


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(body: DepartmentCreate, org: Org, session: OrgSession) -> Department:
    org.require(Permission.MANAGE_ORGANIZATION)
    count = await session.scalar(
        select(func.count(Department.id)).where(Department.organization_id == org.organization_id)
    )
    department = Department(
        organization_id=org.organization_id,
        name=body.name,
        slug=f"{slugify(body.name)}-{uuid.uuid4().hex[:4]}",
        description=body.description,
        sort_order=int(count or 0),
    )
    session.add(department)
    await session.flush()
    return department


@router.get("/departments/{department_id}")
async def get_department(department_id: uuid.UUID, org: Org, session: OrgSession) -> dict[str, Any]:
    department = await session.scalar(
        select(Department).where(
            Department.id == department_id, Department.organization_id == org.organization_id
        )
    )
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    agents = (
        await session.scalars(
            select(Agent).where(
                Agent.organization_id == org.organization_id, Agent.department_id == department.id
            )
        )
    ).all()
    tasks = (
        await session.scalars(
            select(Task)
            .where(Task.organization_id == org.organization_id, Task.department_id == department.id)
            .order_by(Task.updated_at.desc())
            .limit(100)
        )
    ).all()
    objective_ids = {task.objective_id for task in tasks}
    objectives = (
        (await session.scalars(select(Objective).where(Objective.id.in_(objective_ids)))).all()
        if objective_ids
        else []
    )
    agent_ids = [agent.id for agent in agents]
    artifacts = (
        (
            await session.scalars(
                select(Artifact)
                .where(Artifact.organization_id == org.organization_id, Artifact.agent_id.in_(agent_ids))
                .order_by(Artifact.created_at.desc())
                .limit(20)
            )
        ).all()
        if agent_ids
        else []
    )
    activity = (
        await session.scalars(
            select(ActivityEvent)
            .where(
                ActivityEvent.organization_id == org.organization_id,
                (ActivityEvent.department_id == department.id) | ActivityEvent.agent_id.in_(agent_ids),
            )
            .order_by(ActivityEvent.created_at.desc())
            .limit(30)
        )
    ).all()
    completed = [task for task in tasks if task.status == TaskStatus.COMPLETED]
    durations = [
        (task.completed_at - task.started_at).total_seconds()
        for task in completed
        if task.completed_at and task.started_at
    ]
    return {
        "department": DepartmentOut.model_validate(department).model_dump(mode="json"),
        "agents": [AgentOut.model_validate(agent).model_dump(mode="json") for agent in agents],
        "objectives": [ObjectiveOut.model_validate(item).model_dump(mode="json") for item in objectives],
        "active_tasks": [
            TaskOut.model_validate(t).model_dump(mode="json") for t in tasks if t.status in ACTIVE_TASK
        ],
        "recent_completed": [TaskOut.model_validate(t).model_dump(mode="json") for t in completed[:10]],
        "failures": [
            TaskOut.model_validate(t).model_dump(mode="json")
            for t in tasks
            if t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED)
        ],
        "artifacts": [ArtifactOut.model_validate(item).model_dump(mode="json") for item in artifacts],
        "activity": [ActivityOut.model_validate(item).model_dump(mode="json") for item in activity],
        "metrics": {
            "tasks_total": len(tasks),
            "tasks_completed": len(completed),
            "tasks_failed": sum(1 for t in tasks if t.status == TaskStatus.FAILED),
            "average_task_seconds": int(sum(durations) / len(durations)) if durations else None,
        },
    }


# ---------- agents ----------


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(org: Org, session: OrgSession) -> list[Agent]:
    return list(
        (
            await session.scalars(
                select(Agent).where(Agent.organization_id == org.organization_id).order_by(Agent.created_at)
            )
        ).all()
    )


@router.get("/org-chart")
async def org_chart(org: Org, session: OrgSession) -> dict[str, Any]:
    agents = (await session.scalars(select(Agent).where(Agent.organization_id == org.organization_id))).all()
    departments = (
        await session.scalars(select(Department).where(Department.organization_id == org.organization_id))
    ).all()
    relationships = (
        await session.scalars(
            select(AgentRelationship).where(AgentRelationship.organization_id == org.organization_id)
        )
    ).all()
    return {
        "agents": [AgentOut.model_validate(agent).model_dump(mode="json") for agent in agents],
        "departments": [DepartmentOut.model_validate(item).model_dump(mode="json") for item in departments],
        "delegations": [
            {"from": str(item.agent_id), "to": str(item.related_agent_id)} for item in relationships
        ],
    }


@router.get("/tools")
async def list_tools(org: Org) -> list[dict[str, Any]]:
    return [
        {"key": tool.key, "description": tool.description, "risk_level": tool.risk_level.value}
        for tool in TOOL_REGISTRY.values()
    ]


async def _load_agent(session: AsyncSession, org: Org, agent_id: uuid.UUID) -> Agent:
    agent = await session.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == org.organization_id)
    )
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: uuid.UUID, org: Org, session: OrgSession) -> dict[str, Any]:
    agent = await _load_agent(session, org, agent_id)
    tasks = (
        await session.scalars(
            select(Task)
            .where(Task.organization_id == org.organization_id, Task.assigned_agent_id == agent.id)
            .order_by(Task.updated_at.desc())
            .limit(100)
        )
    ).all()
    current = next((task for task in tasks if task.status in ACTIVE_TASK), None)
    current_objective = await session.get(Objective, current.objective_id) if current else None
    messages = (
        await session.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.organization_id == org.organization_id,
                (AgentMessage.sender_agent_id == agent.id) | (AgentMessage.recipient_agent_id == agent.id),
            )
            .order_by(AgentMessage.created_at.desc())
            .limit(30)
        )
    ).all()
    artifacts = (
        await session.scalars(
            select(Artifact)
            .where(Artifact.organization_id == org.organization_id, Artifact.agent_id == agent.id)
            .order_by(Artifact.created_at.desc())
            .limit(30)
        )
    ).all()
    activity = (
        await session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.organization_id == org.organization_id, ActivityEvent.agent_id == agent.id)
            .order_by(ActivityEvent.created_at.desc())
            .limit(30)
        )
    ).all()
    usage = (
        await session.execute(
            select(
                func.coalesce(func.sum(ModelUsage.input_tokens), 0),
                func.coalesce(func.sum(ModelUsage.output_tokens), 0),
                func.coalesce(func.sum(ModelUsage.cost_usd), 0),
                func.count(ModelUsage.id),
            ).where(ModelUsage.organization_id == org.organization_id, ModelUsage.agent_id == agent.id)
        )
    ).one()
    delegates = (
        await session.scalars(
            select(Agent)
            .join(AgentRelationship, AgentRelationship.related_agent_id == Agent.id)
            .where(AgentRelationship.agent_id == agent.id)
        )
    ).all()
    manager = await session.get(Agent, agent.manager_agent_id) if agent.manager_agent_id else None
    department = await session.get(Department, agent.department_id) if agent.department_id else None
    permissions = {p.action_key: p.effect.value for p in agent.permissions}
    return {
        "agent": AgentDetailOut.model_validate(agent).model_dump(mode="json"),
        "department": DepartmentOut.model_validate(department).model_dump(mode="json")
        if department
        else None,
        "manager": AgentOut.model_validate(manager).model_dump(mode="json") if manager else None,
        "delegates": [AgentOut.model_validate(item).model_dump(mode="json") for item in delegates],
        "current_task": TaskOut.model_validate(current).model_dump(mode="json") if current else None,
        "current_objective": ObjectiveOut.model_validate(current_objective).model_dump(mode="json")
        if current_objective
        else None,
        "completed_tasks": [
            TaskOut.model_validate(t).model_dump(mode="json")
            for t in tasks
            if t.status == TaskStatus.COMPLETED
        ][:20],
        "failed_tasks": [
            TaskOut.model_validate(t).model_dump(mode="json") for t in tasks if t.status == TaskStatus.FAILED
        ][:20],
        "stats": {
            "completed": sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in tasks if t.status == TaskStatus.FAILED),
            "revisions": sum(t.revision_count for t in tasks),
        },
        "messages": [MessageOut.model_validate(item).model_dump(mode="json") for item in messages],
        "artifacts": [ArtifactOut.model_validate(item).model_dump(mode="json") for item in artifacts],
        "activity": [ActivityOut.model_validate(item).model_dump(mode="json") for item in activity],
        "tools": [
            {
                "key": tool.tool_key,
                "enabled": tool.enabled,
                "risk_level": TOOL_REGISTRY[tool.tool_key].risk_level.value
                if tool.tool_key in TOOL_REGISTRY
                else None,
                "description": TOOL_REGISTRY[tool.tool_key].description
                if tool.tool_key in TOOL_REGISTRY
                else "",
                "permission": permissions.get(tool.tool_key),
            }
            for tool in agent.tools
        ],
        "usage": {
            "input_tokens": int(usage[0]),
            "output_tokens": int(usage[1]),
            "cost_usd": float(usage[2]),
            "calls": int(usage[3]),
        },
    }


async def _apply_tools(session: AsyncSession, org: Org, agent: Agent, tool_keys: list[str]) -> None:
    unknown = [key for key in tool_keys if key not in TOOL_REGISTRY]
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown tools: {', '.join(unknown)}")
    existing = {tool.tool_key: tool for tool in agent.tools}
    for key, tool in existing.items():
        tool.enabled = key in tool_keys
    for key in tool_keys:
        if key not in existing:
            agent.tools.append(AgentTool(organization_id=org.organization_id, tool_key=key))


@router.post("/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(body: AgentCreate, org: Org, session: OrgSession) -> Agent:
    org.require(Permission.MANAGE_ORGANIZATION)
    if await session.scalar(
        select(Agent.id).where(Agent.organization_id == org.organization_id, Agent.role_key == body.role_key)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "An agent with this role key already exists")
    department = await session.scalar(
        select(Department).where(
            Department.id == body.department_id, Department.organization_id == org.organization_id
        )
    )
    if department is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown department")
    agent = Agent(
        organization_id=org.organization_id,
        department_id=department.id,
        manager_agent_id=body.manager_agent_id,
        name=body.name,
        role_key=body.role_key,
        title=body.title,
        description=body.description,
        system_instructions=body.system_instructions,
        goals=body.goals,
        responsibilities=body.responsibilities,
        tools=[],
    )
    session.add(agent)
    await _apply_tools(session, org, agent, body.tool_keys)
    await session.flush()
    await record_audit(
        session,
        action="agent.create",
        organization_id=org.organization_id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
        target_type="agent",
        target_id=agent.id,
    )
    return agent


@router.patch("/agents/{agent_id}", response_model=AgentDetailOut)
async def update_agent(agent_id: uuid.UUID, body: AgentUpdate, org: Org, session: OrgSession) -> Agent:
    org.require(Permission.MANAGE_ORGANIZATION)
    agent = await _load_agent(session, org, agent_id)
    changes = body.model_dump(exclude_unset=True, exclude={"tool_keys", "delegate_role_keys"})
    for field, value in changes.items():
        setattr(agent, field, value)
    if body.tool_keys is not None:
        await _apply_tools(session, org, agent, body.tool_keys)
    if body.delegate_role_keys is not None:
        targets = (
            await session.scalars(
                select(Agent).where(
                    Agent.organization_id == org.organization_id, Agent.role_key.in_(body.delegate_role_keys)
                )
            )
        ).all()
        existing = (
            await session.scalars(select(AgentRelationship).where(AgentRelationship.agent_id == agent.id))
        ).all()
        for relationship in existing:
            await session.delete(relationship)
        for target in targets:
            session.add(
                AgentRelationship(
                    organization_id=org.organization_id, agent_id=agent.id, related_agent_id=target.id
                )
            )
    await session.flush()
    await record_audit(
        session,
        action="agent.update",
        organization_id=org.organization_id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
        target_type="agent",
        target_id=agent.id,
        details={"fields": sorted(changes) + (["tools"] if body.tool_keys is not None else [])},
    )
    return agent
