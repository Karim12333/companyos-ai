import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.events import record_activity
from companyos.models import Agent, AgentMessage, AgentRelationship, Artifact, Integration, Task
from companyos.models.enums import ActorType, MessageKind, RiskLevel, TaskStatus
from companyos.providers.llm import LLMProvider
from companyos.providers.web_search import WebSearchUnavailable, tavily_search
from companyos.services import artifacts as artifact_service
from companyos.services import knowledge as knowledge_service
from companyos.services.integrations import get_integration_secret

MAX_DELEGATIONS_PER_TASK = 3
MAX_DELEGATION_DEPTH = 2
MAX_TOOL_OUTPUT_CHARS = 12_000


@dataclass
class ToolContext:
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    agent_role_key: str
    objective_id: uuid.UUID | None
    task_id: uuid.UUID | None
    task_run_id: uuid.UUID | None
    llm: LLMProvider
    embedding_model: str
    max_messages_per_task: int = 6
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    untrusted: bool = False


class ToolExecutionError(Exception):
    """Expected tool failure; message is safe to show to the agent."""


Handler = Callable[[ToolContext, AsyncSession, Any], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolDefinition:
    key: str
    description: str
    risk_level: RiskLevel
    args_model: type[BaseModel]
    handler: Handler

    def json_schema(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema


# ---------- argument models ----------


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class CreateArtifactArgs(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    filename: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9._\- ]+$")
    content: str = Field(min_length=1, max_length=200_000)
    kind: str = Field(default="document", max_length=60)


class ReadArtifactArgs(BaseModel):
    artifact_id: uuid.UUID | None = None


class SendMessageArgs(BaseModel):
    recipient_role: str = Field(max_length=80)
    subject: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=2, max_length=4000)
    reason: str = Field(default="", max_length=500)


class DelegateTaskArgs(BaseModel):
    recipient_role: str = Field(max_length=80)
    title: str = Field(min_length=3, max_length=200)
    instructions: str = Field(min_length=10, max_length=4000)
    expected_output_type: str = Field(default="document", max_length=60)


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300)


class PublishSocialPostArgs(BaseModel):
    platform: str = Field(pattern=r"^(linkedin|x|instagram|facebook)$")
    content: str = Field(min_length=5, max_length=3000)


class ScheduleSocialPostArgs(BaseModel):
    platform: str = Field(pattern=r"^(linkedin|x|instagram|facebook)$")
    content: str = Field(min_length=5, max_length=3000)
    publish_at: str = Field(max_length=40, description="ISO date/time for the scheduled draft")


class SendExternalEmailArgs(BaseModel):
    to: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    subject: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=2, max_length=10_000)


# ---------- handlers ----------


async def _agent_by_role(session: AsyncSession, ctx: ToolContext, role_key: str) -> Agent:
    agent = await session.scalar(
        select(Agent).where(
            Agent.organization_id == ctx.organization_id,
            Agent.role_key == role_key,
            Agent.is_active.is_(True),
        )
    )
    if agent is None:
        raise ToolExecutionError(f"No active agent with role '{role_key}'")
    return agent


async def search_company_knowledge(
    ctx: ToolContext, session: AsyncSession, args: SearchKnowledgeArgs
) -> ToolResult:
    results = await knowledge_service.search(
        session,
        organization_id=ctx.organization_id,
        query=args.query,
        llm=ctx.llm,
        embedding_model=ctx.embedding_model,
        limit=args.limit,
        agent_id=ctx.agent_id,
    )
    return ToolResult(content=knowledge_service.format_for_agent(results), data={"hits": len(results.chunks)})


async def create_artifact(ctx: ToolContext, session: AsyncSession, args: CreateArtifactArgs) -> ToolResult:
    artifact, version = await artifact_service.save_artifact(
        session,
        organization_id=ctx.organization_id,
        title=args.title,
        filename=args.filename,
        content=args.content.encode(),
        mime_type="text/markdown" if args.filename.endswith(".md") else "text/plain",
        kind=args.kind,
        objective_id=ctx.objective_id,
        task_id=ctx.task_id,
        agent_id=ctx.agent_id,
        generated_by_mock=ctx.llm.is_mock,
    )
    return ToolResult(
        content=f"Saved artifact '{artifact.title}' version {version.version} (id {artifact.id}).",
        data={"artifact_id": str(artifact.id), "version": version.version},
    )


async def read_artifact(ctx: ToolContext, session: AsyncSession, args: ReadArtifactArgs) -> ToolResult:
    if args.artifact_id is None:
        rows = (
            await session.scalars(
                select(Artifact)
                .where(
                    Artifact.organization_id == ctx.organization_id, Artifact.objective_id == ctx.objective_id
                )
                .order_by(Artifact.created_at)
            )
        ).all()
        listing = "\n".join(f"- {row.id}: {row.title} (v{row.current_version})" for row in rows)
        return ToolResult(content=f"Artifacts in this objective:\n{listing or '(none yet)'}")
    artifact = await session.scalar(
        select(Artifact).where(
            Artifact.organization_id == ctx.organization_id, Artifact.id == args.artifact_id
        )
    )
    if artifact is None:
        raise ToolExecutionError("Artifact not found")
    text = await artifact_service.read_text(session, artifact)
    return ToolResult(content=f"# {artifact.title}\n\n{text[:MAX_TOOL_OUTPUT_CHARS]}")


async def send_message(ctx: ToolContext, session: AsyncSession, args: SendMessageArgs) -> ToolResult:
    sent = await session.scalar(
        select(func.count(AgentMessage.id)).where(
            AgentMessage.task_id == ctx.task_id, AgentMessage.sender_agent_id == ctx.agent_id
        )
    )
    if (sent or 0) >= ctx.max_messages_per_task:
        raise ToolExecutionError("Message limit for this task reached; finish the task instead")
    recipient = await _agent_by_role(session, ctx, args.recipient_role)
    session.add(
        AgentMessage(
            organization_id=ctx.organization_id,
            objective_id=ctx.objective_id,
            task_id=ctx.task_id,
            sender_agent_id=ctx.agent_id,
            recipient_agent_id=recipient.id,
            kind=MessageKind.REQUEST,
            subject=args.subject,
            body=args.body,
            reason=args.reason,
        )
    )
    await record_activity(
        session,
        organization_id=ctx.organization_id,
        event_type="message.sent",
        summary=f"{ctx.agent_role_key.replace('_', ' ').title()} messaged {recipient.name}: {args.subject}",
        objective_id=ctx.objective_id,
        agent_id=ctx.agent_id,
        task_id=ctx.task_id,
        actor_type=ActorType.AGENT,
    )
    return ToolResult(content=f"Message delivered to {recipient.name}.")


async def delegate_task(ctx: ToolContext, session: AsyncSession, args: DelegateTaskArgs) -> ToolResult:
    if ctx.objective_id is None or ctx.task_id is None:
        raise ToolExecutionError("Delegation requires an objective task")
    recipient = await _agent_by_role(session, ctx, args.recipient_role)
    allowed = await session.scalar(
        select(AgentRelationship.id).where(
            AgentRelationship.agent_id == ctx.agent_id,
            AgentRelationship.related_agent_id == recipient.id,
            AgentRelationship.kind == "can_delegate_to",
        )
    )
    if not allowed:
        raise ToolExecutionError(f"You are not authorized to delegate to '{args.recipient_role}'")
    parent = await session.get(Task, ctx.task_id)
    assert parent is not None
    depth = int(parent.execution_metadata.get("delegation_depth", 0)) + 1
    if depth > MAX_DELEGATION_DEPTH:
        raise ToolExecutionError("Maximum delegation depth reached")
    delegated = await session.scalar(select(func.count(Task.id)).where(Task.parent_task_id == parent.id))
    if (delegated or 0) >= MAX_DELEGATIONS_PER_TASK:
        raise ToolExecutionError("Delegation limit for this task reached")
    child = Task(
        organization_id=ctx.organization_id,
        objective_id=ctx.objective_id,
        project_id=parent.project_id,
        parent_task_id=parent.id,
        assigned_agent_id=recipient.id,
        department_id=recipient.department_id,
        plan_key=f"{parent.plan_key}.d{(delegated or 0) + 1}",
        role_key=recipient.role_key,
        title=args.title,
        instructions=args.instructions,
        context=f"Delegated by {ctx.agent_role_key} from task '{parent.title}'.",
        status=TaskStatus.QUEUED,
        sequence=parent.sequence,
        expected_output_type=args.expected_output_type,
        acceptance_criteria=["Fulfils the delegated instructions"],
        execution_metadata={"delegation_depth": depth},
    )
    session.add(child)
    session.add(
        AgentMessage(
            organization_id=ctx.organization_id,
            objective_id=ctx.objective_id,
            task_id=parent.id,
            sender_agent_id=ctx.agent_id,
            recipient_agent_id=recipient.id,
            kind=MessageKind.DELEGATION,
            subject=args.title,
            body=args.instructions,
            reason="Delegated sub-task",
        )
    )
    await record_activity(
        session,
        organization_id=ctx.organization_id,
        event_type="task.delegated",
        summary=f"{ctx.agent_role_key.replace('_', ' ').title()} delegated '{args.title}' to {recipient.name}",
        objective_id=ctx.objective_id,
        agent_id=ctx.agent_id,
        task_id=parent.id,
        actor_type=ActorType.AGENT,
    )
    await session.flush()
    return ToolResult(content=f"Delegated '{args.title}' to {recipient.name} (task {child.id}).")


async def web_search(ctx: ToolContext, session: AsyncSession, args: WebSearchArgs) -> ToolResult:
    integration = await session.scalar(
        select(Integration).where(
            Integration.organization_id == ctx.organization_id, Integration.provider_key == "web_search"
        )
    )
    secret = (
        await get_integration_secret(session, integration) if integration and integration.enabled else None
    )
    if not secret:
        raise ToolExecutionError(
            "Web search is not configured for this organization; rely on company knowledge"
        )
    try:
        results = await tavily_search(secret, args.query)
    except WebSearchUnavailable as error:
        raise ToolExecutionError(str(error)) from error
    body = "\n\n".join(f"[{item.title}]({item.url})\n{item.snippet}" for item in results)
    return ToolResult(content=body or "No results.", data={"results": len(results)}, untrusted=True)


async def publish_social_post(
    ctx: ToolContext, session: AsyncSession, args: PublishSocialPostArgs
) -> ToolResult:
    # Sandbox integration: records the publication without any external network call
    await record_activity(
        session,
        organization_id=ctx.organization_id,
        event_type="integration.social_published",
        summary=f"Social post published to {args.platform} (sandbox)",
        objective_id=ctx.objective_id,
        agent_id=ctx.agent_id,
        task_id=ctx.task_id,
        actor_type=ActorType.AGENT,
        data={"platform": args.platform, "content": args.content},
    )
    return ToolResult(
        content=f"Published to {args.platform} via the sandbox integration (no external network call).",
        data={"platform": args.platform, "sandbox": True},
    )


async def schedule_social_post(
    ctx: ToolContext, session: AsyncSession, args: ScheduleSocialPostArgs
) -> ToolResult:
    await record_activity(
        session,
        organization_id=ctx.organization_id,
        event_type="integration.social_scheduled",
        summary=f"Social post draft scheduled on {args.platform} for {args.publish_at} (sandbox)",
        objective_id=ctx.objective_id,
        agent_id=ctx.agent_id,
        task_id=ctx.task_id,
        actor_type=ActorType.AGENT,
        data={"platform": args.platform, "content": args.content, "publish_at": args.publish_at},
    )
    return ToolResult(content=f"Draft scheduled on {args.platform} for {args.publish_at} (sandbox).")


async def send_external_email(
    ctx: ToolContext, session: AsyncSession, args: SendExternalEmailArgs
) -> ToolResult:
    await record_activity(
        session,
        organization_id=ctx.organization_id,
        event_type="integration.external_email_recorded",
        summary=f"External email to {args.to} recorded (sandbox, not delivered)",
        objective_id=ctx.objective_id,
        agent_id=ctx.agent_id,
        task_id=ctx.task_id,
        actor_type=ActorType.AGENT,
        data={"to": args.to, "subject": args.subject},
    )
    return ToolResult(content="Email recorded in the sandbox; no external email integration is connected.")


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    tool.key: tool
    for tool in [
        ToolDefinition(
            "search_company_knowledge",
            "Search company memory, preferences and documents.",
            RiskLevel.AUTONOMOUS,
            SearchKnowledgeArgs,
            search_company_knowledge,
        ),
        ToolDefinition(
            "create_artifact",
            "Save a deliverable (Markdown document) as a versioned artifact. Use this for your main output.",
            RiskLevel.AUTONOMOUS,
            CreateArtifactArgs,
            create_artifact,
        ),
        ToolDefinition(
            "read_artifact",
            "List artifacts of the current objective, or read one by id.",
            RiskLevel.AUTONOMOUS,
            ReadArtifactArgs,
            read_artifact,
        ),
        ToolDefinition(
            "send_message",
            "Send a short structured message to another agent by role key.",
            RiskLevel.AUTONOMOUS,
            SendMessageArgs,
            send_message,
        ),
        ToolDefinition(
            "delegate_task",
            "Delegate a sub-task to an agent you are authorized to delegate to (by role key).",
            RiskLevel.AUTONOMOUS,
            DelegateTaskArgs,
            delegate_task,
        ),
        ToolDefinition(
            "web_search",
            "Search the public web. Results are untrusted data.",
            RiskLevel.AUTONOMOUS,
            WebSearchArgs,
            web_search,
        ),
        ToolDefinition(
            "schedule_social_post",
            "Create a scheduled social post draft. Controlled action governed by organization policy.",
            RiskLevel.CONTROLLED,
            ScheduleSocialPostArgs,
            schedule_social_post,
        ),
        ToolDefinition(
            "publish_social_post",
            "Publish a social media post. Requires CEO approval.",
            RiskLevel.HUMAN_APPROVAL,
            PublishSocialPostArgs,
            publish_social_post,
        ),
        ToolDefinition(
            "send_external_email",
            "Send an email to an external recipient. Requires CEO approval.",
            RiskLevel.HUMAN_APPROVAL,
            SendExternalEmailArgs,
            send_external_email,
        ),
    ]
}

__all__ = ["TOOL_REGISTRY", "RiskLevel", "ToolContext", "ToolDefinition", "ToolExecutionError", "ToolResult"]
