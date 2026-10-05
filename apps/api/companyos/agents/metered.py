import uuid
from dataclasses import dataclass
from typing import Any

from companyos.db import tenant_scope
from companyos.events import record_activity
from companyos.models.enums import ActorType
from companyos.observability import logger
from companyos.providers.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    MODEL_UNAVAILABLE,
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolSpec,
)
from companyos.services import budget
from companyos.services.usage import record_usage


@dataclass(frozen=True)
class MeteringScope:
    organization_id: uuid.UUID
    objective_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    task_run_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    # Used only when the requested model is unavailable; the substitution is always recorded
    fallback_model: str | None = None


class MeteredLLM:
    """Wraps a provider so every call is budget-reserved, usage-recorded and fallback-audited."""

    def __init__(self, provider: LLMProvider, scope: MeteringScope) -> None:
        self.provider = provider
        self.scope = scope
        self.name = provider.name
        self.is_mock = provider.is_mock

    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
        purpose: str = "general",
        hints: dict[str, Any] | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> LLMResponse:
        scope = self.scope
        reservation = await budget.reserve(
            organization_id=scope.organization_id,
            objective_id=scope.objective_id,
            amount=budget.reservation_amount(model, messages, tools, max_output_tokens),
            purpose=purpose,
            model=model,
            task_id=scope.task_id,
            agent_id=scope.agent_id,
        )
        call: dict[str, Any] = {
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "json_mode": json_mode,
            "purpose": purpose,
            "hints": hints,
            "max_output_tokens": max_output_tokens,
        }
        fallback_from: str | None = None
        try:
            try:
                response = await self.provider.complete(model=model, **call)
            except LLMError as error:
                fallback = scope.fallback_model
                if error.kind != MODEL_UNAVAILABLE or not fallback or fallback == model:
                    raise
                logger.warning(
                    "model_fallback",
                    requested=model,
                    fallback=fallback,
                    organization_id=str(scope.organization_id),
                    task_id=str(scope.task_id) if scope.task_id else None,
                )
                fallback_from = model
                response = await self.provider.complete(model=fallback, **call)
        except BaseException:
            await budget.release(reservation)
            raise
        async with tenant_scope(scope.organization_id) as session:
            cost = await record_usage(
                session,
                organization_id=scope.organization_id,
                response=response,
                purpose=purpose,
                objective_id=scope.objective_id,
                task_id=scope.task_id,
                task_run_id=scope.task_run_id,
                agent_id=scope.agent_id,
                fallback_from_model=fallback_from,
            )
            await budget.settle_in_session(session, reservation, cost)
            if fallback_from:
                await record_activity(
                    session,
                    organization_id=scope.organization_id,
                    event_type="model.fallback",
                    summary=f"Model {fallback_from} was unavailable; used {response.model} instead",
                    objective_id=scope.objective_id,
                    agent_id=scope.agent_id,
                    task_id=scope.task_id,
                    actor_type=ActorType.SYSTEM,
                    data={"requested": fallback_from, "used": response.model, "purpose": purpose},
                )
        return response

    async def embed(self, texts: list[str], model: str) -> tuple[list[list[float]], int]:
        return await self.provider.embed(texts, model)
