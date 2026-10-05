"""CEO escalation activities: detect decisions and apply them to the waiting task."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from temporalio import activity

from companyos.db import tenant_scope
from companyos.events import record_activity
from companyos.models import Escalation, Task
from companyos.models.enums import (
    ActorType,
    ErrorCategory,
    EscalationKind,
    EscalationStatus,
    TaskStatus,
)
from companyos.services.objective_status import refresh_objective_status
from companyos.workflows.activities.shared import fail_task, finish_task, ids
from companyos.workflows.types import EscalationCheck, EscalationOutcome, EscalationRef


@activity.defn(name="resolved_escalations")
async def resolved_escalations(check: EscalationCheck) -> list[str]:
    organization_id = uuid.UUID(check.organization_id)
    async with tenant_scope(organization_id) as session:
        rows = await session.scalars(
            select(Escalation.id).where(
                Escalation.id.in_([uuid.UUID(value) for value in check.escalation_ids]),
                Escalation.status != EscalationStatus.OPEN,
            )
        )
        return [str(row) for row in rows]


def outcome_for(escalation: Escalation) -> str:
    """Maps a CEO decision to what the workflow does next; pure so re-application is deterministic."""
    if escalation.status == EscalationStatus.CANCELLED:
        return "stopped"
    option = escalation.resolution_option or ""
    if option == "fail" or option == "abandon":
        return "stopped"
    if escalation.kind == EscalationKind.REVIEW_EXHAUSTED:
        return "done" if option == "accept" else "rerun"
    if escalation.kind == EscalationKind.ACTION_OUTCOME_UNKNOWN:
        return "retry_action" if option == "retry" else "done"
    return "rerun"


@activity.defn(name="apply_escalation_resolution")
async def apply_escalation_resolution(ref: EscalationRef) -> EscalationOutcome:
    organization_id, task_id, escalation_id = ids(ref.organization_id, ref.task_id, ref.escalation_id)
    async with tenant_scope(organization_id) as session:
        escalation = await session.scalar(
            select(Escalation)
            .where(Escalation.id == escalation_id, Escalation.organization_id == organization_id)
            .with_for_update()
        )
        task = await session.get(Task, task_id)
        if escalation is None or task is None or escalation.task_id != task.id:
            return EscalationOutcome(action="stopped")
        action = outcome_for(escalation)
        if escalation.applied_at is not None:
            # Already applied by an earlier attempt: never repeat side effects
            return EscalationOutcome(action=action)
        escalation.applied_at = datetime.now(UTC)
        decision: dict[str, Any] = next(
            (item for item in escalation.options if item.get("key") == escalation.resolution_option), {}
        )
        if action == "stopped":
            category = (
                ErrorCategory.REVIEW_EXHAUSTED
                if escalation.kind == EscalationKind.REVIEW_EXHAUSTED
                else ErrorCategory.ESCALATION
            )
            note = f": {escalation.resolution_note}" if escalation.resolution_note else ""
            await fail_task(session, task, category, f"Stopped by CEO decision{note}", recoverable=True)
        elif escalation.kind == EscalationKind.REVIEW_EXHAUSTED and action == "done":
            task.execution_metadata = {**task.execution_metadata, "accepted_by_ceo_after_review": True}
            await finish_task(session, task)
        elif escalation.kind == EscalationKind.REVIEW_EXHAUSTED:
            rounds = int(task.execution_metadata.get("ceo_guidance_rounds", 0)) + 1
            task.execution_metadata = {**task.execution_metadata, "ceo_guidance_rounds": rounds}
            task.review_feedback = f"CEO guidance: {escalation.resolution_note}"
            task.status = TaskStatus.READY
        elif escalation.kind == EscalationKind.ACTION_OUTCOME_UNKNOWN:
            task.status = TaskStatus.RUNNING
        else:
            answer = escalation.resolution_note or str(decision.get("label", ""))
            label = decision.get("label", "")
            task.context = (
                f"{task.context}\n\nCEO decision on '{escalation.question[:200]}': {label}"
                + (f" — {answer}" if answer and answer != label else "")
            ).strip()
            task.status = TaskStatus.READY
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="escalation.applied",
            summary=f"Applied CEO decision to '{task.title}': {decision.get('label', action)}",
            objective_id=task.objective_id,
            task_id=task.id,
            agent_id=task.assigned_agent_id,
            actor_type=ActorType.SYSTEM,
            data={"escalation_id": str(escalation.id), "action": action},
        )
        await refresh_objective_status(session, task.objective_id)
        return EscalationOutcome(action=action)
