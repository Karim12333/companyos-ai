"""Seeds the ByteRoot Labs Demo organization. Usage: python -m companyos.seed [--run-objective]"""

import asyncio
import sys

from sqlalchemy import select

from companyos.config import get_settings
from companyos.db import dispose_engine, system_scope, tenant_scope
from companyos.events import close_redis
from companyos.models import CompanyMemory, Organization, Project, User
from companyos.models.enums import MemoryCategory, Priority
from companyos.security import hash_password
from companyos.services.objectives import WorkflowUnavailable, create_objective, start_workflow
from companyos.services.organizations import create_organization

DEMO_EMAIL = "ceo@byteroot.demo"
DEMO_PASSWORD = "CompanyOS-demo-2026"  # noqa: S105 - local demo credential, documented in README
DEMO_ORG = "ByteRoot Labs Demo"
DEMO_OBJECTIVE = (
    "Research and prepare a launch plan for an AI meeting assistant. Include market research, product "
    "definition, technical architecture, marketing messaging and an executive recommendation. "
    "Do not execute external actions."
)

COMPANY_MEMORY = [
    (
        MemoryCategory.IDENTITY,
        "Who we are",
        "ByteRoot Labs builds practical AI products for SMB teams in the GCC and Europe.",
    ),
    (
        MemoryCategory.MISSION,
        "Mission",
        "Help small teams get enterprise-grade leverage from AI without enterprise complexity.",
    ),
    (
        MemoryCategory.BRAND,
        "Voice",
        "Technical, concise and direct. No hype words. Lead with concrete outcomes.",
    ),
    (
        MemoryCategory.POLICY,
        "External communication",
        "Nothing is published or sent externally without CEO approval.",
    ),
    (
        MemoryCategory.PRODUCT,
        "Current products",
        "ByteRoot Assist (support copilot, beta) and ByteRoot Docs (internal search).",
    ),
    (
        MemoryCategory.BUSINESS_RULE,
        "Pricing guardrail",
        "Target SMB pricing between $29 and $99 per seat per month.",
    ),
]


async def seed(run_objective: bool) -> None:
    async with system_scope() as session:
        user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                full_name="Karim (Demo CEO)",
                password_hash=hash_password(DEMO_PASSWORD),
                is_platform_admin=True,
            )
            session.add(user)
            await session.flush()
        organization = await session.scalar(select(Organization).where(Organization.name == DEMO_ORG))
        if organization is None:
            organization = await create_organization(
                session, name=DEMO_ORG, owner_user_id=user.id, owner_email=DEMO_EMAIL, ceo_name="Karim"
            )
            for category, title, content in COMPANY_MEMORY:
                session.add(
                    CompanyMemory(
                        organization_id=organization.id, category=category, title=title, content=content
                    )
                )
            session.add(
                Project(
                    organization_id=organization.id,
                    name="AI Meeting Assistant",
                    description="Explore and prepare the launch of an AI meeting assistant for SMB teams.",
                    created_by_user_id=user.id,
                )
            )
        organization_id, user_id = organization.id, user.id
    print(f"Demo login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"Organization: {DEMO_ORG} ({organization_id})")

    if run_objective:
        async with tenant_scope(organization_id, user_id) as session:
            project_id = await session.scalar(
                select(Project.id).where(Project.organization_id == organization_id)
            )
            objective = await create_objective(
                session,
                organization_id=organization_id,
                user_id=user_id,
                title="AI Meeting Assistant — launch plan",
                instruction=DEMO_OBJECTIVE,
                priority=Priority.HIGH,
                project_id=project_id,
            )
            objective_id = objective.id
        try:
            workflow_id = await start_workflow(organization_id, objective_id)
            print(f"Started objective workflow {workflow_id}")
        except WorkflowUnavailable as error:
            print(f"Objective saved as draft: {error}")
    print(f"Open {get_settings().web_base_url}")


async def main() -> None:
    try:
        await seed("--run-objective" in sys.argv)
    finally:
        await close_redis()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
