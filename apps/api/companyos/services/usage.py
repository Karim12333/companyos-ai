import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.models import ModelUsage, Objective, OrganizationSettings, TaskRun
from companyos.providers.llm import LLMResponse, estimate_cost


class BudgetExceeded(Exception):
    pass


@dataclass
class BudgetState:
    objective_cost: Decimal
    objective_budget: Decimal | None
    daily_cost: Decimal
    daily_budget: Decimal | None


async def daily_cost(session: AsyncSession, organization_id: uuid.UUID) -> Decimal:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = await session.scalar(
        select(func.coalesce(func.sum(ModelUsage.cost_usd), 0)).where(
            ModelUsage.organization_id == organization_id, ModelUsage.created_at >= start
        )
    )
    return Decimal(total or 0)


async def budget_state(
    session: AsyncSession, organization_id: uuid.UUID, objective_id: uuid.UUID | None
) -> BudgetState:
    settings = await session.scalar(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
    )
    objective = await session.get(Objective, objective_id) if objective_id else None
    objective_budget = None
    if objective is not None:
        objective_budget = objective.budget_usd or (settings.objective_budget_usd if settings else None)
    return BudgetState(
        objective_cost=Decimal(objective.cost_usd) if objective else Decimal("0"),
        objective_budget=objective_budget,
        daily_cost=await daily_cost(session, organization_id),
        daily_budget=settings.daily_budget_usd if settings else None,
    )


async def ensure_within_budget(
    session: AsyncSession, organization_id: uuid.UUID, objective_id: uuid.UUID | None
) -> None:
    state = await budget_state(session, organization_id, objective_id)
    if state.objective_budget is not None and state.objective_cost >= state.objective_budget:
        raise BudgetExceeded(f"Objective budget of ${state.objective_budget} exhausted")
    if state.daily_budget is not None and state.daily_cost >= state.daily_budget:
        raise BudgetExceeded(f"Daily AI budget of ${state.daily_budget} exhausted")


async def record_usage(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    response: LLMResponse,
    purpose: str,
    objective_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    task_run_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
) -> Decimal:
    cost = estimate_cost(response.model, response.input_tokens, response.output_tokens)
    session.add(
        ModelUsage(
            organization_id=organization_id,
            objective_id=objective_id,
            task_id=task_id,
            task_run_id=task_run_id,
            agent_id=agent_id,
            provider=response.provider,
            model=response.model,
            purpose=purpose,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=cost,
            latency_ms=response.latency_ms,
        )
    )
    if objective_id:
        await session.execute(
            update(Objective).where(Objective.id == objective_id).values(cost_usd=Objective.cost_usd + cost)
        )
    if task_run_id:
        await session.execute(
            update(TaskRun)
            .where(TaskRun.id == task_run_id)
            .values(
                input_tokens=TaskRun.input_tokens + response.input_tokens,
                output_tokens=TaskRun.output_tokens + response.output_tokens,
                cost_usd=TaskRun.cost_usd + cost,
            )
        )
    await session.flush()
    return cost
