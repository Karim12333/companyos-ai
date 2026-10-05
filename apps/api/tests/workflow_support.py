"""Shared helpers for tests that run the durable objective workflow."""

import asyncio
from collections.abc import Callable
from typing import Any

from companyos.providers.llm import LLMError, LLMResponse
from companyos.providers.mock_llm import MockLLMProvider
from tests.conftest import Tenant

TERMINAL = {"COMPLETED", "COMPLETED_WITH_ISSUES", "FAILED", "CANCELLED"}
OBJECTIVE = {
    "title": "AI meeting assistant launch",
    "instruction": "Research and prepare a launch plan for an AI meeting assistant with marketing messaging.",
}


class SlowMock(MockLLMProvider):
    """Mock model with latency so parallel execution is observable."""

    async def complete(self, **kwargs: Any) -> LLMResponse:
        await asyncio.sleep(0.15)
        return await super().complete(**kwargs)


class FailingProductManager(SlowMock):
    async def complete(self, **kwargs: Any) -> LLMResponse:
        hints = kwargs.get("hints") or {}
        if kwargs.get("purpose") == "execute" and hints.get("role_key") == "product_manager":
            raise LLMError("Model refused the request", recoverable=False)
        return await super().complete(**kwargs)


async def wait_for(
    tenant: Tenant, objective_id: str, predicate: Callable[[dict[str, Any]], bool], seconds: float = 180
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        detail = (await tenant.client.get(tenant.url(f"/objectives/{objective_id}"))).json()
        if predicate(detail):
            return detail
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"Timed out; objective status {detail['objective']['status']}")
        await asyncio.sleep(0.3)


async def create(tenant: Tenant, **overrides: Any) -> str:
    response = await tenant.client.post(
        tenant.url("/objectives"), json={**OBJECTIVE, **overrides}, headers=tenant.headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["workflow_error"] is None
    return response.json()["objective"]["id"]


def pending_approvals(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in detail["approvals"] if item["status"] == "PENDING"]
