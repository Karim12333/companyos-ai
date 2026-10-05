import uuid
from datetime import datetime
from typing import Any

import pytest
from temporalio.client import Client

from companyos.providers.email import RecordingEmailProvider
from companyos.providers.mock_llm import MockLLMProvider
from companyos.services.integrations import set_llm_override
from companyos.services.notification_dispatcher import dispatch_due
from companyos.tools import gateway
from companyos.tools.registry import ToolContext
from tests.conftest import Tenant
from tests.workflow_support import (
    TERMINAL,
    FailingProductManager,
    SlowMock,
    create,
    pending_approvals,
    wait_for,
)


@pytest.fixture(autouse=True)
def slow_mock() -> Any:
    set_llm_override(SlowMock())
    yield
    set_llm_override(None)


async def test_objective_full_lifecycle(
    temporal: Client, tenant: Tenant, mailbox: RecordingEmailProvider
) -> None:
    objective_id = await create(tenant)
    waiting = await wait_for(tenant, objective_id, lambda d: bool(pending_approvals(d)))

    # The plan is persisted as a DAG before execution
    tasks = {task["plan_key"]: task for task in waiting["tasks"]}
    assert len(tasks) == 8
    assert tasks["architecture"]["depends_on"] == [tasks["product_definition"]["id"]]
    # High-risk action is stopped: nothing was published yet
    assert not any(e["event_type"] == "integration.social_published" for e in waiting["activity"])

    approval = pending_approvals(waiting)[0]
    decision = await tenant.client.post(
        tenant.url(f"/approvals/{approval['id']}/decision"), json={"approve": True}, headers=tenant.headers
    )
    assert decision.status_code == 200
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)

    assert done["objective"]["status"] == "COMPLETED"
    tasks = {task["plan_key"]: task for task in done["tasks"]}
    assert all(task["status"] == "COMPLETED" for task in tasks.values())

    # Independent tasks (architecture, positioning) ran in parallel
    first, second = tasks["architecture"], tasks["positioning"]
    assert max(
        datetime.fromisoformat(first["started_at"]), datetime.fromisoformat(second["started_at"])
    ) < min(datetime.fromisoformat(first["completed_at"]), datetime.fromisoformat(second["completed_at"]))
    # Review loop: copy was revised once and accepted
    assert tasks["launch_copy"]["revision_count"] == 1
    kinds = {message["kind"] for message in done["messages"]}
    assert {"delegation", "handoff", "feedback"} <= kinds
    # Approved action executed through the gateway
    assert done["approvals"][0]["execution_result"]["status"] == "executed"
    assert any(e["event_type"] == "integration.social_published" for e in done["activity"])
    # Artifacts and executive report
    summary = done["objective"]["executive_summary"]
    assert summary["tasks_completed"] == 8 and summary["approvals_approved"] == 1
    assert any(a["kind"] == "executive_report" for a in done["artifacts"])
    report_id = summary["report_artifact_id"]
    content = await tenant.client.get(tenant.url(f"/artifacts/{report_id}/content"))
    assert "Executive Report" in content.text
    assert content.headers["content-type"].startswith("text/plain")
    # Emails are delivered by the outbox dispatcher, not inline
    while await dispatch_due():
        pass
    assert any(n.to == tenant.email and "Objective completed" in n.subject for n in mailbox.sent)
    assert any(n.subject.startswith("CompanyOS — Approval required") for n in mailbox.sent)
    hq = (await tenant.client.get(tenant.url("/headquarters"))).json()
    assert hq["health"]["tasks_completed_today"] >= 8


async def test_rejected_action_is_not_executed(temporal: Client, tenant: Tenant) -> None:
    objective_id = await create(tenant)
    waiting = await wait_for(tenant, objective_id, lambda d: bool(pending_approvals(d)))
    approval = pending_approvals(waiting)[0]
    await tenant.client.post(
        tenant.url(f"/approvals/{approval['id']}/decision"),
        json={"approve": False, "note": "Not yet"},
        headers=tenant.headers,
    )
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    assert done["objective"]["executive_summary"]["approvals_rejected"] == 1
    assert not any(e["event_type"] == "integration.social_published" for e in done["activity"])
    second = await tenant.client.post(
        tenant.url(f"/approvals/{approval['id']}/decision"), json={"approve": True}, headers=tenant.headers
    )
    assert second.status_code == 409


async def test_objective_can_forbid_external_actions(temporal: Client, tenant: Tenant) -> None:
    objective_id = await create(tenant, external_actions="deny")
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    assert done["approvals"] == []
    assert done["objective"]["status"] == "COMPLETED"


async def test_failures_are_reported_and_retryable(temporal: Client, tenant: Tenant) -> None:
    set_llm_override(FailingProductManager())
    objective_id = await create(tenant, external_actions="deny")
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    tasks = {task["plan_key"]: task for task in done["tasks"]}
    assert done["objective"]["status"] == "COMPLETED_WITH_ISSUES"
    assert tasks["market_research"]["status"] == "COMPLETED"
    assert tasks["product_definition"]["status"] == "FAILED"
    assert tasks["product_definition"]["error_category"] == "provider"
    assert tasks["architecture"]["status"] == "BLOCKED"
    summary = done["objective"]["executive_summary"]
    assert summary["tasks_failed"] == 7
    assert any(failure["task"] == tasks["product_definition"]["title"] for failure in summary["failures"])
    inbox = (await tenant.client.get(tenant.url("/inbox"), params={"category": "FAILED"})).json()
    assert inbox["items"]

    # Fix the cause and retry: the objective resumes with a new durable run
    set_llm_override(SlowMock())
    retry = await tenant.client.post(
        tenant.url(f"/objectives/{objective_id}/tasks/{tasks['product_definition']['id']}/retry"),
        headers=tenant.headers,
    )
    assert retry.status_code == 200
    resumed = await wait_for(
        tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL and len(d["workflow_runs"]) == 2
    )
    assert resumed["objective"]["status"] == "COMPLETED"


async def test_cancel_objective(temporal: Client, tenant: Tenant) -> None:
    objective_id = await create(tenant)
    await wait_for(tenant, objective_id, lambda d: bool(pending_approvals(d)))
    response = await tenant.client.post(
        tenant.url(f"/objectives/{objective_id}/cancel"), headers=tenant.headers
    )
    assert response.status_code == 200
    done = await wait_for(tenant, objective_id, lambda d: d["objective"]["status"] in TERMINAL)
    assert done["objective"]["status"] == "CANCELLED"
    assert all(approval["status"] == "CANCELLED" for approval in done["approvals"])


async def test_tool_gateway_denies_unauthorized_tools(tenant: Tenant) -> None:
    agents = (await tenant.client.get(tenant.url("/agents"))).json()
    reviewer = next(agent for agent in agents if agent["role_key"] == "reviewer")
    context = ToolContext(
        organization_id=uuid.UUID(tenant.org_id),
        agent_id=uuid.UUID(reviewer["id"]),
        agent_role_key="reviewer",
        objective_id=None,
        task_id=None,
        task_run_id=None,
        llm=MockLLMProvider(),
        embedding_model="local-hash-1536",
    )
    denied = await gateway.invoke(context, "publish_social_post", {"platform": "x", "content": "hello world"})
    assert denied.status == "denied"
    unknown = await gateway.invoke(context, "delete_database", {})
    assert unknown.status == "denied"
    audit = (await tenant.client.get(tenant.url("/audit"))).json()
    assert any(row["action"] == "tool.publish_social_post" and row["outcome"] == "denied" for row in audit)
