import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, update

from companyos.agents.metered import MeteredLLM, MeteringScope
from companyos.agents.runtime import AgentRunInput, run_agent
from companyos.db import tenant_scope
from companyos.models import (
    ActivityEvent,
    Agent,
    BudgetLedger,
    BudgetReservation,
    CompanyMemory,
    ModelUsage,
    Objective,
    OrganizationSettings,
)
from companyos.models.enums import MemoryCategory
from companyos.providers.llm import MODEL_UNAVAILABLE, LLMError, LLMMessage, LLMResponse, ToolCall, ToolSpec
from companyos.providers.mock_llm import MockLLMProvider
from companyos.services import budget, knowledge
from companyos.services.usage import BudgetExceeded
from tests.conftest import Tenant


async def make_objective(tenant: Tenant, budget_usd: str | None = "1.00") -> uuid.UUID:
    organization_id = uuid.UUID(tenant.org_id)
    async with tenant_scope(organization_id) as session:
        objective = Objective(
            organization_id=organization_id,
            title="Budget test",
            instruction="Budget test objective",
            budget_usd=Decimal(budget_usd) if budget_usd else None,
        )
        session.add(objective)
        await session.flush()
        return objective.id


async def ledger(tenant: Tenant, scope: str, key: str) -> BudgetLedger:
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        row = await session.scalar(
            select(BudgetLedger).where(BudgetLedger.scope == scope, BudgetLedger.scope_key == key)
        )
        assert row is not None
        return row


async def try_reserve(
    tenant: Tenant, objective_id: uuid.UUID | None, amount: str
) -> budget.Reservation | None:
    try:
        return await budget.reserve(
            organization_id=uuid.UUID(tenant.org_id),
            objective_id=objective_id,
            amount=Decimal(amount),
            purpose="test",
            model="gpt-4o-mini",
        )
    except BudgetExceeded:
        return None


async def test_concurrent_reservations_never_exceed_objective_budget(tenant: Tenant) -> None:
    objective_id = await make_objective(tenant, "1.00")
    results = await asyncio.gather(*[try_reserve(tenant, objective_id, "0.30") for _ in range(10)])
    granted = [item for item in results if item is not None]
    assert len(granted) == 3
    row = await ledger(tenant, "objective", str(objective_id))
    assert row.reserved_usd == Decimal("0.90")

    # Settling with the real (smaller) cost frees capacity for the next calls
    for reservation in granted:
        async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
            await budget.settle_in_session(session, reservation, Decimal("0.10"))
    row = await ledger(tenant, "objective", str(objective_id))
    assert (row.reserved_usd, row.spent_usd) == (Decimal("0"), Decimal("0.30"))
    second = await asyncio.gather(*[try_reserve(tenant, objective_id, "0.30") for _ in range(5)])
    assert sum(item is not None for item in second) == 2


async def test_daily_budget_is_shared_across_objectives(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    async with tenant_scope(organization_id) as session:
        await session.execute(
            update(OrganizationSettings)
            .where(OrganizationSettings.organization_id == organization_id)
            .values(daily_budget_usd=Decimal("0.50"))
        )
    first, second = await make_objective(tenant, "10"), await make_objective(tenant, "10")
    results = await asyncio.gather(
        *[try_reserve(tenant, objective_id, "0.20") for objective_id in (first, second, first, second)]
    )
    assert sum(item is not None for item in results) == 2


async def test_release_and_stale_expiry_return_capacity(tenant: Tenant) -> None:
    objective_id = await make_objective(tenant, "0.50")
    reservation = await try_reserve(tenant, objective_id, "0.50")
    assert reservation is not None
    assert await try_reserve(tenant, objective_id, "0.01") is None
    await budget.release(reservation)
    crashed = await try_reserve(tenant, objective_id, "0.50")
    assert crashed is not None
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        await session.execute(
            update(BudgetReservation)
            .where(BudgetReservation.id == crashed.id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=1))
        )
    # A reservation orphaned by a crashed worker expires and stops blocking work
    assert await try_reserve(tenant, objective_id, "0.40") is not None


async def test_exhausted_budget_blocks_even_zero_cost_calls(tenant: Tenant) -> None:
    objective_id = await make_objective(tenant, "0.10")
    reservation = await try_reserve(tenant, objective_id, "0.10")
    assert reservation is not None
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        await budget.settle_in_session(session, reservation, Decimal("0.10"))
    assert await try_reserve(tenant, objective_id, "0") is None


class PricedProvider:
    """Deterministic priced model: every call costs exactly the same."""

    name = "fake"
    is_mock = False

    def __init__(self, unavailable: set[str] | None = None) -> None:
        self.unavailable = unavailable or set()
        self.calls: list[str] = []

    async def complete(self, *, model: str, **_: Any) -> LLMResponse:
        self.calls.append(model)
        await asyncio.sleep(0.01)
        if model in self.unavailable:
            raise LLMError(f"model {model} not found", recoverable=False, kind=MODEL_UNAVAILABLE)
        return LLMResponse(
            content="ok",
            tool_calls=[],
            input_tokens=100_000,
            output_tokens=0,
            model=model,
            provider=self.name,
        )

    async def embed(self, texts: list[str], model: str) -> tuple[list[list[float]], int]:
        raise LLMError("embedding endpoint down", recoverable=True)


async def test_parallel_metered_calls_cannot_overspend(tenant: Tenant) -> None:
    # Each call reserves its worst case and actually costs $0.015 (100k input tokens on gpt-4o-mini)
    objective_id = await make_objective(tenant, "0.06")
    llm = MeteredLLM(PricedProvider(), MeteringScope(uuid.UUID(tenant.org_id), objective_id=objective_id))

    async def call() -> bool:
        try:
            await llm.complete(
                model="gpt-4o-mini",
                messages=[LLMMessage(role="user", content="x" * 300_000)],
                max_output_tokens=1,
            )
            return True
        except BudgetExceeded:
            return False

    results = await asyncio.gather(*[call() for _ in range(12)])
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        spent = await session.scalar(
            select(func.sum(ModelUsage.cost_usd)).where(ModelUsage.objective_id == objective_id)
        )
        objective = await session.get(Objective, objective_id)
    assert 0 < sum(results) < 12
    assert Decimal(spent) <= Decimal("0.06")
    assert objective is not None and objective.cost_usd == spent
    row = await ledger(tenant, "objective", str(objective_id))
    assert row.spent_usd == spent and row.reserved_usd == 0


async def test_unavailable_premium_model_falls_back_visibly(tenant: Tenant) -> None:
    objective_id = await make_objective(tenant, "5")
    provider = PricedProvider(unavailable={"gpt-4o"})
    scope = MeteringScope(uuid.UUID(tenant.org_id), objective_id=objective_id, fallback_model="gpt-4o-mini")
    response = await MeteredLLM(provider, scope).complete(
        model="gpt-4o", messages=[LLMMessage(role="user", content="hi")], max_output_tokens=10
    )
    assert response.model == "gpt-4o-mini" and provider.calls == ["gpt-4o", "gpt-4o-mini"]
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        usage = await session.scalar(select(ModelUsage).where(ModelUsage.objective_id == objective_id))
        event = await session.scalar(
            select(ActivityEvent).where(ActivityEvent.event_type == "model.fallback")
        )
    assert usage is not None and usage.fallback_from_model == "gpt-4o"
    assert event is not None

    # Without a configured fallback the failure surfaces and the reservation is released
    with pytest.raises(LLMError):
        await MeteredLLM(
            provider, MeteringScope(uuid.UUID(tenant.org_id), objective_id=objective_id)
        ).complete(model="gpt-4o", messages=[LLMMessage(role="user", content="hi")], max_output_tokens=10)
    row = await ledger(tenant, "objective", str(objective_id))
    assert row.reserved_usd == 0


async def test_embedding_outage_degrades_knowledge_search(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    async with tenant_scope(organization_id) as session:
        session.add(
            CompanyMemory(
                organization_id=organization_id,
                category=MemoryCategory.BRAND,
                title="Voice",
                content="Short.",
            )
        )
        await session.flush()
        results = await knowledge.search(
            session,
            organization_id=organization_id,
            query="brand voice",
            llm=PricedProvider(),
            embedding_model="text-embedding-3-small",
        )
    assert results.degraded and "unavailable" in results.degraded
    assert [fact.title for fact in results.facts] == ["Voice"]
    assert "NOTE" in knowledge.format_for_agent(results)


class RepeatsBrokenTool(MockLLMProvider):
    """Keeps calling an unconfigured tool; records which tools it was offered."""

    def __init__(self) -> None:
        self.offered: list[set[str]] = []

    def _next_execution_step(
        self, messages: list[LLMMessage], tools: list[ToolSpec], hints: dict[str, Any]
    ) -> tuple[list[ToolCall], str | None]:
        names = {tool.name for tool in tools}
        self.offered.append(names)
        if "web_search" in names:
            return [
                ToolCall(id=uuid.uuid4().hex, name="web_search", arguments={"query": "market size"})
            ], None
        return [], "Done without web search; it was unavailable."


async def test_repeatedly_failing_tool_is_withdrawn(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    async with tenant_scope(organization_id) as session:
        researcher = await session.scalar(select(Agent).where(Agent.role_key == "market_researcher"))
        assert researcher is not None
    provider = RepeatsBrokenTool()
    result = await run_agent(
        AgentRunInput(
            organization_id=organization_id,
            agent_id=researcher.id,
            agent_role_key="market_researcher",
            objective_id=None,
            task_id=None,
            task_run_id=None,
            system_prompt="system",
            user_prompt="task",
            tool_keys=["web_search", "create_artifact"],
            llm=provider,
            model="mock-1",
            embedding_model="local-hash-1536",
            temperature=0.2,
            max_iterations=8,
        )
    )
    assert any(step.get("step") == "tool_withdrawn" for step in result.trace)
    assert "web_search" not in provider.offered[-1]
    assert result.final_output.startswith("Done without web search")
