import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.api.deps import Org, OrgSession, SystemSession
from companyos.api.schemas import (
    AIProviderUpdate,
    ApprovalPolicyOut,
    ApprovalPolicyUpdate,
    IntegrationOut,
    MemberAdd,
    MemberOut,
    SecretUpdate,
    SettingsOut,
    SettingsUpdate,
)
from companyos.events import record_audit
from companyos.models import (
    Agent,
    ApprovalPolicy,
    AuditLog,
    Integration,
    ModelUsage,
    Objective,
    OrganizationMember,
    OrganizationSettings,
    Task,
    User,
)
from companyos.models.enums import ActorType, IntegrationStatus, MemberRole, TaskStatus
from companyos.observability import logger
from companyos.providers.llm import LLMError, LLMMessage, OpenAICompatibleProvider
from companyos.rbac import Permission
from companyos.services.integrations import (
    DEFAULT_AI_BASE_URL,
    delete_integration_secret,
    get_integration_secret,
    secret_last4,
    store_integration_secret,
)

router = APIRouter(prefix="/orgs/{org_id}", tags=["administration"])


async def _settings(session: AsyncSession, org: Org) -> OrganizationSettings:
    settings = await session.scalar(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == org.organization_id)
    )
    if settings is None:
        settings = OrganizationSettings(organization_id=org.organization_id)
        session.add(settings)
        await session.flush()
    return settings


async def _audit(
    session: AsyncSession,
    org: Org,
    action: str,
    target_type: str,
    target_id: Any,
    details: dict[str, Any] | None = None,
) -> None:
    await record_audit(
        session,
        action=action,
        organization_id=org.organization_id,
        actor_type=ActorType.USER,
        actor_user_id=org.user.id,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )


# ---------- settings ----------


@router.get("/settings", response_model=SettingsOut)
async def get_settings_route(org: Org, session: OrgSession) -> OrganizationSettings:
    return await _settings(session, org)


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, org: Org, session: OrgSession) -> OrganizationSettings:
    org.require(Permission.MANAGE_SETTINGS)
    settings = await _settings(session, org)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(settings, field, value)
    await _audit(
        session, org, "settings.update", "organization", org.organization_id, {"fields": sorted(changes)}
    )
    return settings


@router.get("/approval-policies", response_model=list[ApprovalPolicyOut])
async def list_policies(org: Org, session: OrgSession) -> list[ApprovalPolicy]:
    query = select(ApprovalPolicy).where(ApprovalPolicy.organization_id == org.organization_id)
    return list((await session.scalars(query.order_by(ApprovalPolicy.action_key))).all())


@router.put("/approval-policies/{policy_id}", response_model=ApprovalPolicyOut)
async def update_policy(
    policy_id: uuid.UUID, body: ApprovalPolicyUpdate, org: Org, session: OrgSession
) -> ApprovalPolicy:
    org.require(Permission.MANAGE_SETTINGS)
    policy = await session.scalar(
        select(ApprovalPolicy).where(
            ApprovalPolicy.id == policy_id, ApprovalPolicy.organization_id == org.organization_id
        )
    )
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Policy not found")
    policy.requires_approval = body.requires_approval
    await _audit(
        session,
        org,
        "approval_policy.update",
        "approval_policy",
        policy.id,
        {"requires_approval": body.requires_approval},
    )
    return policy


# ---------- integrations ----------


async def _integration_out(session: AsyncSession, integration: Integration) -> IntegrationOut:
    last4 = await secret_last4(session, integration)
    return IntegrationOut(
        id=integration.id,
        provider_key=integration.provider_key,
        name=integration.name,
        enabled=integration.enabled,
        status=integration.status.value,
        scopes=list(integration.scopes or []),
        config=integration.config or {},
        has_secret=last4 is not None,
        secret_last4=last4,
        health_message=integration.health_message,
        last_checked_at=integration.last_checked_at,
    )


async def _integration(session: AsyncSession, org: Org, provider_key: str) -> Integration:
    integration = await session.scalar(
        select(Integration).where(
            Integration.organization_id == org.organization_id, Integration.provider_key == provider_key
        )
    )
    if integration is None:
        integration = Integration(
            organization_id=org.organization_id, provider_key=provider_key, name=provider_key
        )
        session.add(integration)
        await session.flush()
    return integration


@router.get("/integrations", response_model=list[IntegrationOut])
async def list_integrations(org: Org, session: OrgSession) -> list[IntegrationOut]:
    rows = (
        await session.scalars(
            select(Integration)
            .where(Integration.organization_id == org.organization_id)
            .order_by(Integration.created_at)
        )
    ).all()
    return [await _integration_out(session, row) for row in rows]


@router.put("/integrations/ai-provider", response_model=IntegrationOut)
async def update_ai_provider(body: AIProviderUpdate, org: Org, session: OrgSession) -> IntegrationOut:
    org.require(Permission.MANAGE_INTEGRATIONS)
    integration = await _integration(session, org, "ai_provider")
    integration.name = "AI Provider (OpenAI-compatible)"
    integration.enabled = body.enabled
    integration.config = {
        "base_url": body.base_url.rstrip("/"),
        "default_model": body.default_model,
        "premium_model": body.premium_model,
        "embedding_model": body.embedding_model,
    }
    if body.api_key:
        await store_integration_secret(session, integration, body.api_key.strip(), org.user.id)
    elif not await secret_last4(session, integration):
        integration.status = IntegrationStatus.NOT_CONFIGURED
    if not body.enabled:
        integration.status = IntegrationStatus.DISABLED
    # Only metadata goes to the audit log, never the key
    await _audit(
        session,
        org,
        "integration.ai_provider.update",
        "integration",
        integration.id,
        {"key_changed": bool(body.api_key), **integration.config},
    )
    await session.flush()
    return await _integration_out(session, integration)


@router.delete("/integrations/{provider_key}/secret", response_model=IntegrationOut)
async def remove_secret(provider_key: str, org: Org, session: OrgSession) -> IntegrationOut:
    org.require(Permission.MANAGE_INTEGRATIONS)
    integration = await _integration(session, org, provider_key)
    await delete_integration_secret(session, integration)
    await _audit(session, org, f"integration.{provider_key}.secret_removed", "integration", integration.id)
    return await _integration_out(session, integration)


@router.put("/integrations/web-search", response_model=IntegrationOut)
async def update_web_search(body: SecretUpdate, org: Org, session: OrgSession) -> IntegrationOut:
    org.require(Permission.MANAGE_INTEGRATIONS)
    integration = await _integration(session, org, "web_search")
    integration.name = "Web Search (Tavily)"
    integration.enabled = True
    await store_integration_secret(session, integration, body.api_key.strip(), org.user.id)
    await _audit(session, org, "integration.web_search.update", "integration", integration.id)
    return await _integration_out(session, integration)


@router.post("/integrations/ai-provider/test", response_model=IntegrationOut)
async def test_ai_provider(org: Org, session: OrgSession) -> IntegrationOut:
    org.require(Permission.MANAGE_INTEGRATIONS)
    integration = await _integration(session, org, "ai_provider")
    secret = await get_integration_secret(session, integration)
    if not secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No API key configured")
    config = integration.config or {}
    provider = OpenAICompatibleProvider(
        api_key=secret, base_url=config.get("base_url") or DEFAULT_AI_BASE_URL
    )
    try:
        await provider.complete(
            model=config.get("default_model") or "gpt-4o-mini",
            messages=[LLMMessage(role="user", content="Reply with the single word: ok")],
            purpose="health_check",
        )
        integration.status = IntegrationStatus.CONNECTED
        integration.health_message = "Connection succeeded"
    except LLMError as error:
        integration.status = IntegrationStatus.ERROR
        integration.health_message = str(error)[:500]
        logger.info("ai_provider_test_failed", organization_id=str(org.organization_id))
    integration.last_checked_at = datetime.now(UTC)
    await session.flush()
    return await _integration_out(session, integration)


# ---------- members ----------


@router.get("/members", response_model=list[MemberOut])
async def list_members(org: Org, session: OrgSession) -> list[MemberOut]:
    rows = (
        await session.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == org.organization_id)
            .order_by(OrganizationMember.created_at)
        )
    ).all()
    return [
        MemberOut(
            id=m.id,
            user_id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=m.role.value,
            created_at=m.created_at,
        )
        for m, u in rows
    ]


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def add_member(body: MemberAdd, org: Org, session: OrgSession) -> MemberOut:
    org.require(Permission.MANAGE_MEMBERS)
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No account with this email. Ask them to sign up first."
        )
    if await session.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == org.organization_id, OrganizationMember.user_id == user.id
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member")
    member = OrganizationMember(
        organization_id=org.organization_id, user_id=user.id, role=MemberRole(body.role)
    )
    session.add(member)
    await session.flush()
    await _audit(session, org, "member.add", "user", user.id, {"role": body.role})
    return MemberOut(
        id=member.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=member.role.value,
        created_at=member.created_at,
    )


# ---------- analytics ----------


@router.get("/analytics")
async def analytics(
    org: Org, session: OrgSession, days: int = Query(default=30, ge=1, le=180)
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    base = (ModelUsage.organization_id == org.organization_id, ModelUsage.created_at >= since)
    day = cast(ModelUsage.created_at, Date)
    by_day = (
        await session.execute(
            select(
                day,
                func.sum(ModelUsage.input_tokens + ModelUsage.output_tokens),
                func.sum(ModelUsage.cost_usd),
            )
            .where(*base)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    by_agent = (
        await session.execute(
            select(
                Agent.name,
                func.sum(ModelUsage.input_tokens + ModelUsage.output_tokens),
                func.sum(ModelUsage.cost_usd),
                func.count(ModelUsage.id),
            )
            .join(Agent, Agent.id == ModelUsage.agent_id)
            .where(*base)
            .group_by(Agent.name)
            .order_by(func.sum(ModelUsage.cost_usd).desc())
        )
    ).all()
    by_model = (
        await session.execute(
            select(
                ModelUsage.model,
                func.sum(ModelUsage.input_tokens),
                func.sum(ModelUsage.output_tokens),
                func.sum(ModelUsage.cost_usd),
            )
            .where(*base)
            .group_by(ModelUsage.model)
        )
    ).all()
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(ModelUsage.input_tokens), 0),
                func.coalesce(func.sum(ModelUsage.output_tokens), 0),
                func.coalesce(func.sum(ModelUsage.cost_usd), 0),
                func.count(ModelUsage.id),
            ).where(*base)
        )
    ).one()
    task_status = dict(
        (
            await session.execute(
                select(Task.status, func.count(Task.id))
                .where(Task.organization_id == org.organization_id, Task.created_at >= since)
                .group_by(Task.status)
            )
        ).all()
    )
    objective_status = dict(
        (
            await session.execute(
                select(Objective.status, func.count(Objective.id))
                .where(Objective.organization_id == org.organization_id, Objective.created_at >= since)
                .group_by(Objective.status)
            )
        ).all()
    )
    completed = task_status.get(TaskStatus.COMPLETED, 0)
    failed = task_status.get(TaskStatus.FAILED, 0)
    return {
        "days": days,
        "totals": {
            "input_tokens": int(totals[0]),
            "output_tokens": int(totals[1]),
            "cost_usd": float(totals[2]),
            "llm_calls": int(totals[3]),
        },
        "by_day": [{"date": str(d), "tokens": int(t or 0), "cost_usd": float(c or 0)} for d, t, c in by_day],
        "by_agent": [
            {"agent": n, "tokens": int(t or 0), "cost_usd": float(c or 0), "calls": int(k)}
            for n, t, c, k in by_agent
        ],
        "by_model": [
            {"model": m, "input_tokens": int(i or 0), "output_tokens": int(o or 0), "cost_usd": float(c or 0)}
            for m, i, o, c in by_model
        ],
        "tasks": {key.value: value for key, value in task_status.items()},
        "objectives": {key.value: value for key, value in objective_status.items()},
        "task_success_rate": round(completed / (completed + failed), 3) if completed + failed else None,
    }


@router.get("/audit")
async def audit_logs(
    org: Org, session: SystemSession, limit: int = Query(default=100, le=500)
) -> list[dict[str, Any]]:
    org.require(Permission.MANAGE_SETTINGS)
    rows = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == org.organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": row.id,
            "action": row.action,
            "actor_type": row.actor_type.value,
            "actor_user_id": row.actor_user_id,
            "actor_agent_id": row.actor_agent_id,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "outcome": row.outcome,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in rows
    ]
