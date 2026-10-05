import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.models import (
    Agent,
    AgentRelationship,
    AgentTool,
    ApprovalPolicy,
    Department,
    Integration,
    Organization,
    OrganizationMember,
    OrganizationSettings,
)
from companyos.models.enums import IntegrationStatus, MemberRole
from companyos.templates import TEMPLATES, OrganizationTemplate
from companyos.tools.registry import TOOL_REGISTRY, RiskLevel

# Integrations every organization starts with (configured later in Settings → Integrations)
DEFAULT_INTEGRATIONS = [
    ("ai_provider", "AI Provider (OpenAI-compatible)", IntegrationStatus.NOT_CONFIGURED),
    ("web_search", "Web Search (Tavily)", IntegrationStatus.NOT_CONFIGURED),
    ("social_sandbox", "Social Publishing (Sandbox)", IntegrationStatus.CONNECTED),
]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "org"


async def unique_slug(session: AsyncSession, name: str) -> str:
    base = slugify(name)
    candidate = base
    while await session.scalar(select(Organization.id).where(Organization.slug == candidate)):
        candidate = f"{base}-{uuid.uuid4().hex[:4]}"
    return candidate


async def create_organization(
    session: AsyncSession,
    *,
    name: str,
    owner_user_id: uuid.UUID,
    owner_email: str,
    template_key: str = "software_ai_company",
    ceo_name: str | None = None,
) -> Organization:
    # Must run in system scope: the tenant does not exist yet
    template = TEMPLATES[template_key]
    organization = Organization(name=name, slug=await unique_slug(session, name), template_key=template_key)
    session.add(organization)
    await session.flush()
    session.add(
        OrganizationMember(organization_id=organization.id, user_id=owner_user_id, role=MemberRole.OWNER)
    )
    session.add(
        OrganizationSettings(
            organization_id=organization.id, notification_emails=[owner_email], ceo_name=ceo_name
        )
    )
    await instantiate_template(session, organization.id, template)
    for action_key, tool in TOOL_REGISTRY.items():
        if tool.risk_level == RiskLevel.CONTROLLED:
            session.add(
                ApprovalPolicy(
                    organization_id=organization.id,
                    action_key=action_key,
                    requires_approval=True,
                    description=tool.description,
                )
            )
    for provider_key, label, status in DEFAULT_INTEGRATIONS:
        session.add(
            Integration(organization_id=organization.id, provider_key=provider_key, name=label, status=status)
        )
    await session.flush()
    return organization


async def instantiate_template(
    session: AsyncSession, organization_id: uuid.UUID, template: OrganizationTemplate
) -> dict[str, Agent]:
    """Idempotent: creates what is missing and only adds tools/delegations, so it also upgrades orgs."""
    departments = {
        department.slug: department
        for department in (
            await session.scalars(select(Department).where(Department.organization_id == organization_id))
        ).all()
    }
    for spec in template.departments:
        if spec.slug not in departments:
            department = Department(
                organization_id=organization_id,
                name=spec.name,
                slug=spec.slug,
                description=spec.description,
                sort_order=spec.sort_order,
            )
            session.add(department)
            departments[spec.slug] = department
    await session.flush()

    agents = {
        agent.role_key: agent
        for agent in (
            await session.scalars(select(Agent).where(Agent.organization_id == organization_id))
        ).all()
    }
    created: set[str] = set()
    for agent_spec in template.agents:
        existing = agents.get(agent_spec.role_key)
        if existing is not None:
            if existing.template_key == template.key:
                # Template-managed agents gain new template tools; customizations are never removed
                owned = {tool.tool_key for tool in existing.tools}
                for tool in agent_spec.tools:
                    if tool not in owned:
                        existing.tools.append(AgentTool(organization_id=organization_id, tool_key=tool))
            continue
        agent = Agent(
            organization_id=organization_id,
            department_id=departments[agent_spec.department].id,
            name=agent_spec.name,
            role_key=agent_spec.role_key,
            title=agent_spec.title,
            description=agent_spec.description,
            system_instructions=agent_spec.instructions,
            goals=agent_spec.goals,
            responsibilities=agent_spec.responsibilities,
            is_coordinator=agent_spec.is_coordinator,
            use_premium_model=agent_spec.use_premium_model,
            template_key=template.key,
            tools=[AgentTool(organization_id=organization_id, tool_key=tool) for tool in agent_spec.tools],
        )
        session.add(agent)
        agents[agent_spec.role_key] = agent
        created.add(agent_spec.role_key)
    await session.flush()

    relations: set[tuple[uuid.UUID, uuid.UUID]] = {
        (row[0], row[1])
        for row in (
            await session.execute(
                select(AgentRelationship.agent_id, AgentRelationship.related_agent_id).where(
                    AgentRelationship.organization_id == organization_id
                )
            )
        ).all()
    }
    for agent_spec in template.agents:
        agent = agents[agent_spec.role_key]
        if agent_spec.role_key in created:
            if agent_spec.manager and agent_spec.manager in agents:
                agent.manager_agent_id = agents[agent_spec.manager].id
            department = departments[agent_spec.department]
            if agent_spec.is_department_manager and department.manager_agent_id is None:
                department.manager_agent_id = agent.id
        for delegate in agent_spec.delegates_to:
            target = agents.get(delegate)
            if target is not None and (agent.id, target.id) not in relations:
                session.add(
                    AgentRelationship(
                        organization_id=organization_id,
                        agent_id=agent.id,
                        related_agent_id=target.id,
                        kind="can_delegate_to",
                    )
                )
                relations.add((agent.id, target.id))
    await session.flush()
    return agents
