"""Concurrency-safe AI budget enforcement: reserve worst-case cost before a model call, settle after.

Every model call reserves its maximum possible cost (estimated input + the hard output-token cap).
A reservation succeeds only through a conditional UPDATE (`spent + reserved + amount <= limit`) on the
objective and daily ledger rows. Row locks serialize concurrent agents, so parallel calls can never
collectively pass a limit. After the call the reservation is replaced by the actual cost; failed calls
release it; reservations orphaned by a crash expire after STALE_AFTER.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.db import tenant_scope
from companyos.models import BudgetLedger, BudgetReservation, Objective, OrganizationSettings
from companyos.providers.llm import LLMMessage, ToolSpec, estimate_cost
from companyos.services.usage import BudgetExceeded

STALE_AFTER = timedelta(minutes=30)
UNLIMITED = Decimal("1000000")
# Characters per token is ~4 for English; 3 over-estimates on purpose so reservations are an upper bound
CHARS_PER_TOKEN = 3
PER_MESSAGE_OVERHEAD_TOKENS = 12


@dataclass(frozen=True)
class Reservation:
    id: uuid.UUID
    organization_id: uuid.UUID
    objective_id: uuid.UUID | None
    daily_key: str
    amount: Decimal


def today_key() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def estimate_input_tokens(messages: list[LLMMessage], tools: list[ToolSpec] | None) -> int:
    characters = sum(
        len(message.content or "") + sum(len(json.dumps(call.arguments)) for call in message.tool_calls)
        for message in messages
    )
    characters += sum(len(tool.description) + len(json.dumps(tool.parameters)) for tool in tools or [])
    return characters // CHARS_PER_TOKEN + PER_MESSAGE_OVERHEAD_TOKENS * len(messages)


def reservation_amount(
    model: str, messages: list[LLMMessage], tools: list[ToolSpec] | None, max_output_tokens: int
) -> Decimal:
    return estimate_cost(model, estimate_input_tokens(messages, tools), max_output_tokens)


async def _ledger_id(
    session: AsyncSession, organization_id: uuid.UUID, scope: str, key: str, limit: Decimal
) -> uuid.UUID:
    await session.execute(
        insert(BudgetLedger)
        .values(id=uuid.uuid4(), organization_id=organization_id, scope=scope, scope_key=key, limit_usd=limit)
        .on_conflict_do_nothing(constraint="uq_budget_ledger_scope")
    )
    ledger_id = await session.scalar(
        select(BudgetLedger.id).where(
            BudgetLedger.organization_id == organization_id,
            BudgetLedger.scope == scope,
            BudgetLedger.scope_key == key,
        )
    )
    assert ledger_id is not None
    return ledger_id


async def _try_reserve(session: AsyncSession, ledger_id: uuid.UUID, amount: Decimal, limit: Decimal) -> bool:
    # Atomic check-and-increment; an exhausted ledger also blocks zero-cost calls
    row = await session.execute(
        text(
            "UPDATE budget_ledgers SET reserved_usd = reserved_usd + :amount, limit_usd = :limit, "
            "updated_at = now() WHERE id = :id AND spent_usd + reserved_usd + :amount <= :limit "
            "AND spent_usd + reserved_usd < :limit RETURNING id"
        ),
        {"id": ledger_id, "amount": amount, "limit": limit},
    )
    return row.scalar() is not None


async def _adjust(
    session: AsyncSession,
    organization_id: uuid.UUID,
    scope: str,
    key: str,
    reserved_delta: Decimal,
    spent_delta: Decimal,
) -> None:
    await session.execute(
        update(BudgetLedger)
        .where(
            BudgetLedger.organization_id == organization_id,
            BudgetLedger.scope == scope,
            BudgetLedger.scope_key == key,
        )
        .values(
            reserved_usd=BudgetLedger.reserved_usd + reserved_delta,
            spent_usd=BudgetLedger.spent_usd + spent_delta,
        )
    )


async def expire_stale(session: AsyncSession, organization_id: uuid.UUID) -> int:
    stale = (
        await session.scalars(
            select(BudgetReservation)
            .where(
                BudgetReservation.organization_id == organization_id,
                BudgetReservation.status == "reserved",
                BudgetReservation.created_at < datetime.now(UTC) - STALE_AFTER,
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    for reservation in stale:
        reservation.status = "expired"
        await _return_amount(session, reservation, Decimal("0"))
    return len(stale)


async def _return_amount(session: AsyncSession, reservation: BudgetReservation, actual: Decimal) -> None:
    await _adjust(
        session, reservation.organization_id, "daily", reservation.daily_key, -reservation.amount_usd, actual
    )
    if reservation.objective_id:
        await _adjust(
            session,
            reservation.organization_id,
            "objective",
            str(reservation.objective_id),
            -reservation.amount_usd,
            actual,
        )


async def reserve(
    *,
    organization_id: uuid.UUID,
    objective_id: uuid.UUID | None,
    amount: Decimal,
    purpose: str,
    model: str,
    task_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
) -> Reservation:
    """Reserves `amount` against the daily and objective budgets, or raises BudgetExceeded."""
    daily_key = today_key()
    async with tenant_scope(organization_id) as session:
        await expire_stale(session, organization_id)
        settings = await session.scalar(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
        )
        daily_limit = Decimal(settings.daily_budget_usd) if settings else UNLIMITED
        daily_ledger = await _ledger_id(session, organization_id, "daily", daily_key, daily_limit)
        # Fixed lock order (daily, then objective) prevents deadlocks between concurrent reservations
        if not await _try_reserve(session, daily_ledger, amount, daily_limit):
            raise BudgetExceeded(f"Daily AI budget of ${daily_limit} would be exceeded")
        if objective_id is not None:
            objective = await session.get(Objective, objective_id)
            objective_limit = (
                Decimal(objective.budget_usd)
                if objective and objective.budget_usd is not None
                else Decimal(settings.objective_budget_usd)
                if settings
                else UNLIMITED
            )
            objective_ledger = await _ledger_id(
                session, organization_id, "objective", str(objective_id), objective_limit
            )
            if not await _try_reserve(session, objective_ledger, amount, objective_limit):
                # Raising rolls back the daily reservation in the same transaction
                raise BudgetExceeded(f"Objective budget of ${objective_limit} would be exceeded")
        reservation = BudgetReservation(
            organization_id=organization_id,
            objective_id=objective_id,
            task_id=task_id,
            agent_id=agent_id,
            daily_key=daily_key,
            purpose=purpose,
            model=model,
            amount_usd=amount,
        )
        session.add(reservation)
        await session.flush()
        return Reservation(reservation.id, organization_id, objective_id, daily_key, amount)


async def settle_in_session(session: AsyncSession, reservation: Reservation, actual: Decimal) -> None:
    row = await session.scalar(
        select(BudgetReservation).where(BudgetReservation.id == reservation.id).with_for_update()
    )
    if row is None or row.status != "reserved":
        # Already expired/settled: only record the real spend so totals stay true
        await _adjust(
            session, reservation.organization_id, "daily", reservation.daily_key, Decimal("0"), actual
        )
        if reservation.objective_id:
            await _adjust(
                session,
                reservation.organization_id,
                "objective",
                str(reservation.objective_id),
                Decimal("0"),
                actual,
            )
        return
    row.status = "settled"
    row.actual_usd = actual
    row.settled_at = datetime.now(UTC)
    await _return_amount(session, row, actual)


async def release(reservation: Reservation) -> None:
    async with tenant_scope(reservation.organization_id) as session:
        row = await session.scalar(
            select(BudgetReservation).where(BudgetReservation.id == reservation.id).with_for_update()
        )
        if row is None or row.status != "reserved":
            return
        row.status = "released"
        row.settled_at = datetime.now(UTC)
        await _return_amount(session, row, Decimal("0"))
