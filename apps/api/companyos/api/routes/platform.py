from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text

from companyos.api.deps import AuthContext, SystemSession, require_platform_admin
from companyos.db import get_engine
from companyos.events import get_redis
from companyos.models import (
    AuditLog,
    ModelUsage,
    Notification,
    Objective,
    Organization,
    OrganizationMember,
    Task,
    User,
    WorkflowRun,
)
from companyos.models.enums import NotificationStatus, ObjectiveStatus, TaskStatus
from companyos.workflows.client import get_temporal_client

router = APIRouter(prefix="/platform", tags=["platform"])
health_router = APIRouter(prefix="/health", tags=["health"])
PlatformAdmin = Annotated[AuthContext, Depends(require_platform_admin)]


async def dependency_health() -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as error:
        checks["database"] = f"error: {error.__class__.__name__}"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as error:
        checks["redis"] = f"error: {error.__class__.__name__}"
    try:
        client = await get_temporal_client()
        await client.service_client.check_health()
        checks["temporal"] = "ok"
    except Exception as error:
        checks["temporal"] = f"error: {error.__class__.__name__}"
    return checks


@health_router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/ready")
async def ready() -> dict[str, Any]:
    checks = await dependency_health()
    return {"status": "ok" if all(v == "ok" for v in checks.values()) else "degraded", "checks": checks}


@router.get("/overview")
async def overview(admin: PlatformAdmin, session: SystemSession) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=30)
    organizations = (
        await session.execute(
            select(
                Organization,
                select(func.count(OrganizationMember.id))
                .where(OrganizationMember.organization_id == Organization.id)
                .scalar_subquery(),
                select(func.count(Objective.id))
                .where(Objective.organization_id == Organization.id)
                .scalar_subquery(),
                select(func.coalesce(func.sum(ModelUsage.cost_usd), 0))
                .where(ModelUsage.organization_id == Organization.id, ModelUsage.created_at >= since)
                .scalar_subquery(),
            ).order_by(Organization.created_at.desc())
        )
    ).all()
    failed_runs = (
        await session.execute(
            select(
                Objective.id,
                Objective.title,
                Objective.status,
                Objective.organization_id,
                Objective.completed_at,
            )
            .where(Objective.status.in_([ObjectiveStatus.FAILED, ObjectiveStatus.COMPLETED_WITH_ISSUES]))
            .order_by(Objective.completed_at.desc().nullslast())
            .limit(20)
        )
    ).all()
    failed_tasks = await session.scalar(select(func.count(Task.id)).where(Task.status == TaskStatus.FAILED))
    running = await session.scalar(
        select(func.count(WorkflowRun.id)).where(WorkflowRun.finished_at.is_(None))
    )
    failed_emails = (
        await session.scalars(
            select(Notification)
            .where(Notification.status == NotificationStatus.FAILED)
            .order_by(Notification.created_at.desc())
            .limit(10)
        )
    ).all()
    audit = (await session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(30))).all()
    return {
        "health": await dependency_health(),
        "totals": {
            "organizations": len(organizations),
            "users": await session.scalar(select(func.count(User.id))) or 0,
            "objectives": await session.scalar(select(func.count(Objective.id))) or 0,
            "running_workflows": running or 0,
            "failed_tasks": failed_tasks or 0,
            "cost_30d_usd": float(sum(row[3] for row in organizations)),
        },
        "organizations": [
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "plan": org.plan,
                "status": org.status,
                "members": members,
                "objectives": objectives,
                "cost_30d_usd": float(cost),
                "created_at": org.created_at,
            }
            for org, members, objectives, cost in organizations
        ],
        "workflow_failures": [
            {
                "objective_id": r[0],
                "title": r[1],
                "status": r[2].value,
                "organization_id": r[3],
                "completed_at": r[4],
            }
            for r in failed_runs
        ],
        "failed_notifications": [
            {
                "id": n.id,
                "kind": n.kind,
                "recipient": n.recipient,
                "error": n.error,
                "created_at": n.created_at,
            }
            for n in failed_emails
        ],
        "audit": [
            {
                "id": a.id,
                "action": a.action,
                "organization_id": a.organization_id,
                "outcome": a.outcome,
                "created_at": a.created_at,
            }
            for a in audit
        ],
    }
