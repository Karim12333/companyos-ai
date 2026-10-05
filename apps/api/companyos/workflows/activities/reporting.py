"""Objective finalization, executive report and notification activities."""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity

from companyos.agents.metered import MeteredLLM, MeteringScope
from companyos.agents.prompts import agent_system_prompt
from companyos.agents.reporting import write_report
from companyos.db import tenant_scope
from companyos.events import record_activity
from companyos.models import (
    Agent,
    Approval,
    Artifact,
    Department,
    Escalation,
    InboxItem,
    Objective,
    Organization,
    Task,
    WorkflowRun,
)
from companyos.models.enums import (
    OBJECTIVE_TERMINAL,
    ActorType,
    ApprovalStatus,
    InboxCategory,
    ObjectiveStatus,
    ReviewStatus,
    Severity,
    TaskStatus,
)
from companyos.providers.llm import LLMError
from companyos.services import artifacts as artifact_service
from companyos.services.escalations import cancel_open_escalations
from companyos.services.integrations import resolve_ai
from companyos.services.notifications import notify_objective_finished
from companyos.services.reports import render_report_markdown
from companyos.services.usage import BudgetExceeded
from companyos.workflows.activities.shared import (
    agent_by_role,
    fallback_for,
    ids,
    model_for,
    now,
    set_agent_idle_if_free,
)
from companyos.workflows.types import (
    FinalizeInput,
    ObjectiveInput,
)


@activity.defn(name="finalize_objective")
async def finalize_objective(data: FinalizeInput) -> str:
    organization_id, objective_id = ids(data.organization_id, data.objective_id)
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
                .values(action_required=False, resolved_at=now())
            )
            await cancel_open_escalations(session, objective_id)
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
            # Work the CEO accepted despite reviewer rejection is delivered, but it is an issue
            ceo_accepted = [t for t in completed if t.execution_metadata.get("accepted_by_ceo_after_review")]
            if not failed and not ceo_accepted:
                status = ObjectiveStatus.COMPLETED
            elif not failed:
                status = ObjectiveStatus.COMPLETED_WITH_ISSUES
            else:
                status = ObjectiveStatus.COMPLETED_WITH_ISSUES if completed else ObjectiveStatus.FAILED
        stats = await _objective_stats(session, objective, tasks, status)
        reporter = await agent_by_role(session, organization_id, "executive_reporter")
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
        reporter_fallback = fallback_for(reporter, ai)

    narrative_payload: dict[str, Any]
    try:
        metered = MeteredLLM(
            ai.provider,
            MeteringScope(
                organization_id=organization_id,
                objective_id=objective_id,
                agent_id=reporter_id,
                fallback_model=reporter_fallback,
            ),
        )
        narrative, _ = await write_report(
            llm=metered,
            model=reporter_model,
            system_prompt=system_prompt,
            stats=stats,
            deliverables="\n\n".join(deliverables),
        )
        narrative_payload = narrative.model_dump()
    except (LLMError, BudgetExceeded) as error:
        narrative_payload = {
            "headline": f"{stats['objective_title']} — {status.value}",
            "overall_assessment": f"Narrative unavailable ({error}). The facts below are authoritative.",
            "key_findings": [],
            "recommendation": "Review deliverables directly.",
            "next_actions": [],
            "risks": [],
        }

    async with tenant_scope(organization_id) as session:
        objective = await session.get(Objective, objective_id)
        assert objective is not None
        summary = {**stats, "narrative": narrative_payload}
        objective.status = status
        objective.executive_summary = summary
        objective.completed_at = now()
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
            .values(status=status.value.lower(), finished_at=now())
        )
        # The outcome email is written to the outbox in the same transaction as the report
        await notify_objective_finished(session, organization_id, objective_id)
        # Only this objective's agents, and only if they are not busy on another objective
        for agent_id in {task.assigned_agent_id for task in tasks if task.assigned_agent_id}:
            await set_agent_idle_if_free(session, agent_id)
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
    escalations = (
        await session.scalars(
            select(Escalation).where(Escalation.objective_id == objective.id).order_by(Escalation.created_at)
        )
    ).all()
    started = objective.started_at or objective.created_at
    revisions = sum(task.revision_count for task in tasks)
    return {
        "objective_title": objective.title,
        "status": status.value,
        "duration_seconds": int((now() - started).total_seconds()),
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
        "escalations": [
            {
                "id": str(item.id),
                "kind": item.kind.value,
                "question": item.question[:500],
                "status": item.status.value,
                "decision": item.resolution_option,
                "note": item.resolution_note[:500],
            }
            for item in escalations
        ],
        "accepted_by_ceo_after_review": [
            t.title for t in tasks if t.execution_metadata.get("accepted_by_ceo_after_review")
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
    organization_id, objective_id = ids(data.organization_id, data.objective_id)
    async with tenant_scope(organization_id) as session:
        await notify_objective_finished(session, organization_id, objective_id)
