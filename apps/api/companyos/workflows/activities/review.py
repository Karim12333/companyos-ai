"""Reviewer activity."""

from sqlalchemy import select, update
from temporalio import activity

from companyos.agents.prompts import agent_system_prompt
from companyos.agents.review import review_deliverable
from companyos.db import tenant_scope
from companyos.events import record_activity
from companyos.models import (
    Agent,
    AgentMessage,
    Artifact,
    Organization,
    OrganizationSettings,
    Task,
)
from companyos.models.enums import (
    ActorType,
    MessageKind,
    ReviewStatus,
    TaskStatus,
)
from companyos.services import artifacts as artifact_service
from companyos.services.integrations import resolve_ai
from companyos.services.usage import record_usage
from companyos.workflows.activities.shared import (
    agent_by_role,
    finish_task,
    ids,
    model_for,
    preferences,
)
from companyos.workflows.types import (
    ReviewResult,
    TaskRef,
)


@activity.defn(name="review_task")
async def review_task(ref: TaskRef) -> ReviewResult:
    organization_id, objective_id, task_id = ids(ref.organization_id, ref.objective_id, ref.task_id)
    async with tenant_scope(organization_id) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        reviewer = await agent_by_role(session, organization_id, "reviewer")
        if reviewer is None:
            await finish_task(session, task)
            return ReviewResult(verdict="accept", feedback="No reviewer configured")
        organization = await session.get(Organization, organization_id)
        settings = await session.scalar(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
        )
        assert organization is not None
        task.status = TaskStatus.REVIEW
        artifacts = (await session.scalars(select(Artifact).where(Artifact.task_id == task.id))).all()
        deliverable = "\n\n".join(
            [await artifact_service.read_text(session, artifact) for artifact in artifacts]
        )
        ai = await resolve_ai(session, organization_id)
        system_prompt = agent_system_prompt(
            reviewer, organization.name, await preferences(session, organization_id, reviewer.id)
        )
        reviewer_id, author_id = reviewer.id, task.assigned_agent_id
        snapshot = (
            task.title,
            task.instructions,
            list(task.acceptance_criteria),
            task.role_key,
            task.revision_count,
        )
        max_revisions = settings.max_review_revisions if settings else 2
        reviewer_model = model_for(reviewer, ai)

    verdict, response = await review_deliverable(
        llm=ai.provider,
        model=reviewer_model,
        system_prompt=system_prompt,
        task_title=snapshot[0],
        instructions=snapshot[1],
        criteria=snapshot[2],
        deliverable=deliverable or "(no deliverable produced)",
        hints={"role_key": snapshot[3], "revision_count": snapshot[4]},
    )

    async with tenant_scope(organization_id) as session:
        await record_usage(
            session,
            organization_id=organization_id,
            response=response,
            purpose="review",
            objective_id=objective_id,
            task_id=task_id,
            agent_id=reviewer_id,
        )
        task = await session.get(Task, task_id)
        reviewer = await session.get(Agent, reviewer_id)
        author = await session.get(Agent, author_id) if author_id else None
        assert task is not None and reviewer is not None
        wants_revision = verdict.verdict == "revise"
        if wants_revision and task.revision_count < max_revisions:
            task.revision_count += 1
            task.review_feedback = verdict.feedback
            await session.execute(
                update(Artifact)
                .where(Artifact.task_id == task.id)
                .values(review_status=ReviewStatus.CHANGES_REQUESTED)
            )
            session.add(
                AgentMessage(
                    organization_id=organization_id,
                    objective_id=objective_id,
                    task_id=task.id,
                    sender_agent_id=reviewer.id,
                    recipient_agent_id=author_id,
                    kind=MessageKind.FEEDBACK,
                    subject=f"Revision requested: {task.title}",
                    body=verdict.feedback,
                    reason="; ".join(verdict.issues)[:500],
                )
            )
            await record_activity(
                session,
                organization_id=organization_id,
                event_type="review.revision_requested",
                summary=f"Reviewer requested revision on {task.title}",
                objective_id=objective_id,
                agent_id=reviewer.id,
                task_id=task.id,
                actor_type=ActorType.AGENT,
                data={"feedback": verdict.feedback, "score": verdict.score},
            )
            return ReviewResult(verdict="revise", feedback=verdict.feedback)

        task.execution_metadata = {
            **task.execution_metadata,
            "review_score": verdict.score,
            **({"accepted_after_max_revisions": True} if wants_revision else {}),
        }
        await session.execute(
            update(Artifact).where(Artifact.task_id == task.id).values(review_status=ReviewStatus.ACCEPTED)
        )
        session.add(
            AgentMessage(
                organization_id=organization_id,
                objective_id=objective_id,
                task_id=task.id,
                sender_agent_id=reviewer.id,
                recipient_agent_id=author_id,
                kind=MessageKind.FEEDBACK,
                subject=f"Approved: {task.title}",
                body=verdict.feedback or "Meets the acceptance criteria.",
                reason=f"Review score {verdict.score}/10",
            )
        )
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="review.accepted",
            summary=f"Reviewer approved {task.title}" + (f" by {author.name}" if author else ""),
            objective_id=objective_id,
            agent_id=reviewer.id,
            task_id=task.id,
            actor_type=ActorType.AGENT,
            data={"score": verdict.score},
        )
        await finish_task(session, task)
        return ReviewResult(verdict="accept", feedback=verdict.feedback)
