import json
import uuid
from typing import Any

from sqlalchemy import select
from temporalio.client import Client

from companyos.agents.reporting import normalize_assessment
from companyos.db import tenant_scope
from companyos.models import Agent
from companyos.providers.llm import LLMResponse
from companyos.providers.mock_llm import MockLLMProvider
from companyos.services.integrations import set_llm_override
from companyos.tools import gateway
from companyos.tools.registry import ToolContext
from tests.conftest import Tenant
from tests.workflow_support import TERMINAL, SlowMock, create, wait_for


def test_every_criterion_gets_one_trusted_assessment() -> None:
    narrative = {
        "criteria_assessment": [
            {"criterion": "B", "status": "pass", "evidence": "doc", "evidence_refs": ["E-1", "E-fake"]},
            {"criterion": "unrelated", "status": "MAYBE"},
        ],
        "goal_assessment": {"status": "WINNING"},
        "recommendation_evidence": ["E-1", "E-2"],
    }
    result = normalize_assessment(narrative, ["A", "B", "C"], {"E-1"})
    statuses = [(item["criterion"], item["status"]) for item in result["criteria_assessment"]]
    assert statuses == [("A", "UNKNOWN"), ("B", "PASS"), ("C", "UNKNOWN")]
    assert result["criteria_assessment"][1]["evidence_refs"] == ["E-1"]
    assert result["goal_assessment"]["status"] == "UNKNOWN"
    assert result["recommendation_evidence"] == ["E-1"]


async def test_sourced_facts_require_a_retrieved_source(tenant: Tenant) -> None:
    organization_id = uuid.UUID(tenant.org_id)
    async with tenant_scope(organization_id) as session:
        researcher = await session.scalar(select(Agent).where(Agent.role_key == "market_researcher"))
        assert researcher is not None
    context = ToolContext(
        organization_id=organization_id,
        agent_id=researcher.id,
        agent_role_key="market_researcher",
        objective_id=None,
        task_id=None,
        task_run_id=None,
        llm=MockLLMProvider(),
        embedding_model="local-hash-1536",
    )
    invented = {
        "items": [{"kind": "sourced_fact", "claim": "Market is $4B", "source_url": "https://made.up/x"}]
    }
    assert (await gateway.invoke(context, "record_evidence", invented)).status == "error"
    context.extra["seen_sources"] = {"https://real.example/report"}
    sourced = {
        "items": [
            {"kind": "sourced_fact", "claim": "Market is $4B", "source_url": "https://real.example/report"}
        ]
    }
    assumption = {
        "items": [{"kind": "assumption", "claim": "Buyers prefer monthly plans", "confidence": "low"}]
    }
    assert (await gateway.invoke(context, "record_evidence", sourced)).status == "executed"
    assert (await gateway.invoke(context, "record_evidence", assumption)).status == "executed"


class CriterionFails(SlowMock):
    async def complete(self, **kwargs: Any) -> LLMResponse:
        response = await super().complete(**kwargs)
        if kwargs.get("purpose") == "report":
            payload = json.loads(response.content or "{}")
            for item in payload["criteria_assessment"]:
                item["status"] = "FAIL"
            response.content = json.dumps(payload)
        return response


async def test_completed_tasks_do_not_mean_goal_achieved(temporal: Client, tenant: Tenant) -> None:
    set_llm_override(CriterionFails())
    try:
        objective_id = await create(
            tenant, external_actions="deny", success_criteria=["At least 3 pilot customers named"]
        )
        done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    finally:
        set_llm_override(None)
    objective = done["objective"]
    assert all(task["status"] == "COMPLETED" for task in done["tasks"])
    assert objective["acceptance_criteria"][0] == "At least 3 pilot customers named"
    assessments = objective["executive_summary"]["narrative"]["criteria_assessment"]
    assert {item["status"] for item in assessments} == {"FAIL"}
    assert objective["status"] == "COMPLETED_WITH_ISSUES"
    kinds = {item["kind"] for item in done["evidence"]}
    assert kinds == {"assumption", "conclusion"}
