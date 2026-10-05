import json
import uuid
from typing import Any

import pytest
from temporalio.client import Client

from companyos.providers.llm import LLMMessage, LLMResponse, ToolCall, ToolSpec
from companyos.services.integrations import set_llm_override
from tests.conftest import Tenant
from tests.workflow_support import TERMINAL, SlowMock, create, wait_for


class CopyAlwaysRejected(SlowMock):
    """The reviewer never accepts the copywriter's work."""

    async def complete(self, **kwargs: Any) -> LLMResponse:
        hints = kwargs.get("hints") or {}
        if kwargs.get("purpose") == "review" and hints.get("role_key") == "copywriter":
            response = await super().complete(**kwargs)
            response.content = json.dumps(
                {"verdict": "revise", "score": 4, "feedback": "Still too generic.", "issues": ["generic"]}
            )
            return response
        return await super().complete(**kwargs)


class ProductManagerAsksCEO(SlowMock):
    """The product manager escalates once, then works normally after the CEO answers."""

    def _next_execution_step(
        self, messages: list[LLMMessage], tools: list[ToolSpec], hints: dict[str, Any]
    ) -> tuple[list[ToolCall], str | None]:
        prompt = " ".join(message.content or "" for message in messages)
        used = {call.name for message in messages for call in message.tool_calls}
        if hints.get("role_key") == "product_manager" and "CEO decision" not in prompt and not used:
            return [
                ToolCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name="escalate_to_ceo",
                    arguments={
                        "kind": "decision_required",
                        "question": "Which customer segment should the MVP target first?",
                        "context": "Research supports both SMB and enterprise.",
                        "options": [{"label": "SMB teams"}, {"label": "Enterprise"}],
                    },
                )
            ], None
        return super()._next_execution_step(messages, tools, hints)


@pytest.fixture
async def strict_reviews(tenant: Tenant) -> Any:
    await tenant.client.patch(
        tenant.url("/settings"), json={"max_review_revisions": 0}, headers=tenant.headers
    )
    set_llm_override(CopyAlwaysRejected())
    yield
    set_llm_override(None)


def escalations_open(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in detail["escalations"] if item["status"] == "OPEN"]


async def resolve(tenant: Tenant, escalation_id: str, option: str, note: str = "") -> Any:
    return await tenant.client.post(
        tenant.url(f"/escalations/{escalation_id}/resolve"),
        json={"option": option, "note": note},
        headers=tenant.headers,
    )


async def test_review_exhaustion_escalates_and_ceo_accepts(
    temporal: Client, tenant: Tenant, strict_reviews: Any
) -> None:
    objective_id = await create(tenant, external_actions="deny")
    waiting = await wait_for(tenant, objective_id, lambda d: bool(escalations_open(d)))
    escalation = escalations_open(waiting)[0]
    assert escalation["kind"] == "review_exhausted"
    assert {option["key"] for option in escalation["options"]} == {"accept", "revise", "fail"}

    # Visible everywhere: task, objective, inbox, activity
    waiting = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] == "NEEDS_ATTENTION")
    task = next(t for t in waiting["tasks"] if t["id"] == escalation["task_id"])
    assert task["status"] == "NEEDS_ATTENTION"
    assert task["revision_count"] == 0  # never exceeds the configured limit
    inbox = (await tenant.client.get(tenant.url("/inbox"), params={"category": "DECISION_REQUIRED"})).json()
    assert inbox["items"][0]["link"] == f"/escalations/{escalation['id']}"
    assert any(e["event_type"] == "escalation.created" for e in waiting["activity"])

    assert (await resolve(tenant, escalation["id"], "accept")).status_code == 200
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    summary = done["objective"]["executive_summary"]
    assert done["objective"]["status"] == "COMPLETED_WITH_ISSUES"
    assert summary["accepted_by_ceo_after_review"] == [task["title"]]
    assert summary["escalations"][0]["decision"] == "accept"
    assert (await resolve(tenant, escalation["id"], "fail")).status_code == 409


async def test_review_exhaustion_ceo_stops_task(
    temporal: Client, tenant: Tenant, strict_reviews: Any
) -> None:
    objective_id = await create(tenant, external_actions="deny")
    waiting = await wait_for(tenant, objective_id, lambda d: bool(escalations_open(d)))
    escalation = escalations_open(waiting)[0]
    await resolve(tenant, escalation["id"], "fail")
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    task = next(t for t in done["tasks"] if t["id"] == escalation["task_id"])
    assert task["status"] == "FAILED"
    assert task["error_category"] == "review_exhausted"
    assert done["objective"]["status"] == "COMPLETED_WITH_ISSUES"


async def test_review_exhaustion_ceo_guidance_runs_another_round(
    temporal: Client, tenant: Tenant, strict_reviews: Any
) -> None:
    objective_id = await create(tenant, external_actions="deny")
    first = escalations_open(await wait_for(tenant, objective_id, lambda d: bool(escalations_open(d))))[0]
    assert (await resolve(tenant, first["id"], "revise")).status_code == 409  # guidance is mandatory
    await resolve(tenant, first["id"], "revise", "Lead with a measurable outcome for CTOs.")
    second = escalations_open(
        await wait_for(
            tenant, objective_id, lambda d: any(e["id"] != first["id"] for e in escalations_open(d))
        )
    )[0]
    detail = (await tenant.client.get(tenant.url(f"/objectives/{objective_id}"))).json()
    task = next(t for t in detail["tasks"] if t["id"] == first["task_id"])
    assert task["execution_metadata"]["ceo_guidance_rounds"] == 1
    assert task["revision_count"] == 0
    await resolve(tenant, second["id"], "accept")
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    assert len(done["objective"]["executive_summary"]["escalations"]) == 2


async def test_agent_escalation_pauses_only_affected_work_and_resumes(
    temporal: Client, tenant: Tenant
) -> None:
    set_llm_override(ProductManagerAsksCEO())
    try:
        objective_id = await create(tenant, external_actions="deny")
        waiting = await wait_for(tenant, objective_id, lambda d: bool(escalations_open(d)))
        escalation = escalations_open(waiting)[0]
        assert escalation["kind"] == "decision_required"
        labels = [option["label"] for option in escalation["options"]]
        assert labels[:2] == ["SMB teams", "Enterprise"]
        tasks = {t["plan_key"]: t for t in waiting["tasks"]}
        assert tasks["market_research"]["status"] == "COMPLETED"
        assert tasks["product_definition"]["status"] == "NEEDS_ATTENTION"

        await resolve(tenant, escalation["id"], "option_1", "Focus on 10-50 person teams.")
        done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
        assert done["objective"]["status"] == "COMPLETED"
        product = next(t for t in done["tasks"] if t["plan_key"] == "product_definition")
        assert product["status"] == "COMPLETED"
        assert any(e["event_type"] == "escalation.applied" for e in done["activity"])
    finally:
        set_llm_override(None)


async def test_resolving_unknown_escalation_returns_404(tenant: Tenant) -> None:
    missing = await resolve(tenant, str(uuid.uuid4()), "accept")
    assert missing.status_code == 404
