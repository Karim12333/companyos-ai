import json
import uuid
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.config import get_settings
from companyos.models import ActivityEvent, AuditLog
from companyos.models.enums import ActorType
from companyos.observability import logger

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


def org_channel(organization_id: uuid.UUID | str) -> str:
    return f"org:{organization_id}:events"


def queue_realtime(
    session: AsyncSession, organization_id: uuid.UUID, kind: str, payload: dict[str, Any]
) -> None:
    # Published only after the transaction commits (see db.session_scope)
    session.info.setdefault("realtime_events", []).append((str(organization_id), {"kind": kind, **payload}))


async def publish_pending(events: list[tuple[str, dict[str, Any]]]) -> None:
    if not events:
        return
    try:
        client = get_redis()
        for organization_id, payload in events:
            await client.publish(org_channel(organization_id), json.dumps(payload, default=str))
    except Exception as error:
        # Realtime is best-effort; the UI also polls, so log and continue
        logger.warning("realtime_publish_failed", error=str(error))


async def record_activity(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    event_type: str,
    summary: str,
    objective_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    actor_type: ActorType = ActorType.SYSTEM,
    actor_user_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> ActivityEvent:
    event = ActivityEvent(
        organization_id=organization_id,
        event_type=event_type,
        summary=summary,
        objective_id=objective_id,
        project_id=project_id,
        department_id=department_id,
        agent_id=agent_id,
        task_id=task_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        data=data or {},
    )
    session.add(event)
    queue_realtime(
        session,
        organization_id,
        "activity",
        {
            "event_type": event_type,
            "summary": summary,
            "objective_id": objective_id,
            "agent_id": agent_id,
            "task_id": task_id,
        },
    )
    return event


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    organization_id: uuid.UUID | None,
    actor_type: ActorType,
    actor_user_id: uuid.UUID | None = None,
    actor_agent_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    correlation_id: str | None = None,
) -> None:
    session.add(
        AuditLog(
            organization_id=organization_id,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            actor_agent_id=actor_agent_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            outcome=outcome,
            details=details or {},
            ip_address=ip_address,
            correlation_id=correlation_id,
        )
    )
