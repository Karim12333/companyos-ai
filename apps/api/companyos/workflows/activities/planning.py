"""Chief of Staff planning activity."""

from sqlalchemy import func, select, update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from companyos.agents.planning import PlanningError, RoleOption, create_plan
from companyos.agents.prompts import agent_system_prompt
from companyos.db import tenant_scope
from companyos.events import record_activity
from companyos.models import (
    Agent,
    AgentMessage,
    Department,
    Objective,
    Organization,
    Task,
    TaskDependency,
)
from companyos.models.enums import (
    ActorType,
    AgentStatus,
    MessageKind,
    ObjectiveStatus,
)
from companyos.providers.llm import LLMError
from companyos.services.integrations import resolve_ai
from companyos.workflows.activities.shared import (
    NON_RETRYABLE,
    agent_by_role,
    ids,
    model_for,
    preferences,
)
from companyos.workflows.types import (
    ObjectiveInput,
)


@activity.defn(name="plan_objective")
async def plan_objective(data: ObjectiveInput) -> int:
    organization_id, objective_id = ids(data.organization_id, data.objective_id)
    async with tenant_scope(organization_id) as session:
        existing = await session.scalar(select(func.count(Task.id)).where(Task.objective_id == objective_id))
        if existing:
            return int(existing)
        objective = await session.get(Objective, objective_id)
        organization = await session.get(Organization, organization_id)
        assert objective is not None and organization is not None
        coordinator = (
            await session.get(Agent, objective.coordinator_agent_id)
            if objective.coordinator_agent_id
            else None
        )
        coordinator = coordinator or await agent_by_role(session, organization_id, "chief_of_staff")
        if coordinator is None:
            raise ApplicationError(
                "No Chief of Staff agent configured", type=NON_RETRYABLE, non_retryable=True
            )
        agents = (
            await session.scalars(
                select(Agent).where(Agent.organization_id == organization_id, Agent.is_active.is_(True))
            )
        ).all()
        departments = {
            department.id: department.name
            for department in (
                await session.scalars(select(Department).where(Department.organization_id == organization_id))
            ).all()
        }
        roles = [
            RoleOption(
                agent.role_key, agent.title, departments.get(agent.department_id, ""), agent.responsibilities
            )
            for agent in agents
            if not agent.is_coordinator
        ]
        ai = await resolve_ai(session, organization_id)
        system_prompt = agent_system_prompt(
            coordinator, organization.name, await preferences(session, organization_id, coordinator.id)
        )
        objective_snapshot = (objective.title, objective.instruction, objective.context)
        coordinator_id = coordinator.id
        coordinator.status = AgentStatus.WORKING

    try:
        plan = await create_plan(
            organization_id=organization_id,
            objective_id=objective_id,
            coordinator_agent_id=coordinator_id,
            system_prompt=system_prompt,
            objective_title=objective_snapshot[0],
            instruction=objective_snapshot[1],
            context=objective_snapshot[2],
            roles=roles,
            llm=ai.provider,
            model=model_for(coordinator, ai),
        )
    except PlanningError as error:
        raise ApplicationError(str(error), type=NON_RETRYABLE, non_retryable=True) from error
    except LLMError as error:
        if error.recoverable:
            raise
        raise ApplicationError(str(error), type=NON_RETRYABLE, non_retryable=True) from error

    async with tenant_scope(organization_id) as session:
        objective = await session.get(Objective, objective_id)
        assert objective is not None
        agents_by_role = {
            agent.role_key: agent
            for agent in (
                await session.scalars(select(Agent).where(Agent.organization_id == organization_id))
            ).all()
        }
        created: dict[str, Task] = {}
        for index, planned in enumerate(plan.tasks):
            agent = agents_by_role[planned.role]
            task = Task(
                organization_id=organization_id,
                objective_id=objective_id,
                project_id=objective.project_id,
                assigned_agent_id=agent.id,
                department_id=agent.department_id,
                plan_key=planned.key,
                role_key=planned.role,
                title=planned.title,
                instructions=planned.instructions,
                priority=planned.priority,
                sequence=index,
                expected_output_type=planned.expected_output_type,
                acceptance_criteria=planned.acceptance_criteria,
                requires_review=planned.requires_review,
            )
            session.add(task)
            created[planned.key] = task
        await session.flush()
        for planned in plan.tasks:
            for dependency in planned.depends_on:
                session.add(
                    TaskDependency(
                        organization_id=organization_id,
                        task_id=created[planned.key].id,
                        depends_on_task_id=created[dependency].id,
                    )
                )
            session.add(
                AgentMessage(
                    organization_id=organization_id,
                    objective_id=objective_id,
                    task_id=created[planned.key].id,
                    sender_agent_id=coordinator_id,
                    recipient_agent_id=created[planned.key].assigned_agent_id,
                    kind=MessageKind.DELEGATION,
                    subject=f"Assignment: {planned.title}",
                    body=planned.instructions,
                    reason="Planned by the Chief of Staff",
                )
            )
        objective.status = ObjectiveStatus.RUNNING
        objective.current_stage = "Executing"
        objective.plan_summary = plan.summary
        await session.execute(update(Agent).where(Agent.id == coordinator_id).values(status=AgentStatus.IDLE))
        await record_activity(
            session,
            organization_id=organization_id,
            event_type="objective.planned",
            summary=f"Chief of Staff created a plan with {len(plan.tasks)} tasks",
            objective_id=objective_id,
            agent_id=coordinator_id,
            actor_type=ActorType.AGENT,
        )
        return len(plan.tasks)
