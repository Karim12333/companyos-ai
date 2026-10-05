import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.events import queue_realtime
from companyos.models import Objective, Task
from companyos.models.enums import OBJECTIVE_TERMINAL, ObjectiveStatus, TaskStatus


async def refresh_objective_status(session: AsyncSession, objective_id: uuid.UUID | None) -> None:
    """Derives the live objective status from its tasks; terminal objectives are never touched."""
    if objective_id is None:
        return
    objective = await session.get(Objective, objective_id)
    if objective is None or objective.status in OBJECTIVE_TERMINAL:
        return
    await session.flush()
    statuses = set(
        (await session.scalars(select(Task.status).where(Task.objective_id == objective_id))).all()
    )
    total = await session.scalar(select(Task.id).where(Task.objective_id == objective_id).limit(1))
    if objective.is_paused:
        objective.status, objective.current_stage = ObjectiveStatus.PAUSED, "Paused"
    elif TaskStatus.NEEDS_ATTENTION in statuses:
        objective.status, objective.current_stage = (
            ObjectiveStatus.NEEDS_ATTENTION,
            "Waiting for a CEO decision",
        )
    elif TaskStatus.WAITING_FOR_APPROVAL in statuses:
        objective.status, objective.current_stage = (
            ObjectiveStatus.WAITING_FOR_APPROVAL,
            "Waiting for CEO approval",
        )
    elif TaskStatus.REVIEW in statuses:
        objective.status, objective.current_stage = ObjectiveStatus.REVIEWING, "Reviewing deliverables"
    elif total is not None:
        objective.status, objective.current_stage = ObjectiveStatus.RUNNING, "Executing"
    queue_realtime(session, objective.organization_id, "objective", {"objective_id": str(objective_id)})
