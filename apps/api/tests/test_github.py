import json
import uuid
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import select

from companyos.db import tenant_scope
from companyos.models import Agent, AuditLog
from companyos.providers.github import set_github_transport
from companyos.providers.mock_llm import MockLLMProvider
from companyos.tools import gateway
from companyos.tools.registry import ToolContext
from tests.conftest import Tenant

TOKEN = "ghp_testtoken_1234567890abcdef"
REPO = "Karim12333/byterootlabs"


class FakeGitHub:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        path, method = request.url.path, request.method
        self.requests.append((method, path))
        branch = {
            "name": "main",
            "protected": True,
            "commit": {"sha": "abc123", "commit": {"tree": {"sha": "tree1"}}},
        }
        routes = {
            ("GET", f"/repos/{REPO}"): {
                "full_name": REPO,
                "default_branch": "main",
                "language": "TypeScript",
            },
            ("GET", f"/repos/{REPO}/contents/README.md"): {
                "type": "file",
                "sha": "f1",
                "content": "IyBCeXRlUm9vdA==",
            },
            ("GET", f"/repos/{REPO}/branches/main"): branch,
            ("GET", f"/repos/{REPO}/branches/feature/landing"): {
                **branch,
                "name": "feature/landing",
                "protected": False,
            },
            ("POST", f"/repos/{REPO}/git/refs"): {"ref": "refs/heads/feature/landing"},
            ("POST", f"/repos/{REPO}/git/trees"): {"sha": "tree2"},
            ("POST", f"/repos/{REPO}/git/commits"): {"sha": "def4567890"},
            ("PATCH", f"/repos/{REPO}/git/refs/heads/feature/landing"): {"ref": "ok"},
            ("POST", f"/repos/{REPO}/pulls"): {"number": 7, "html_url": f"https://github.com/{REPO}/pull/7"},
            ("GET", "/user"): {"login": "Karim12333"},
        }
        if (method, path) in routes:
            return httpx.Response(200, json=routes[(method, path)])
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def github() -> Iterator[FakeGitHub]:
    fake = FakeGitHub()
    set_github_transport(httpx.MockTransport(fake.handler))
    yield fake
    set_github_transport(None)


async def connect(tenant: Tenant, write: bool = True) -> None:
    response = await tenant.client.put(
        tenant.url("/integrations/github"),
        json={"token": TOKEN, "allowed_repos": [REPO], "default_branch": "main", "write_enabled": write},
        headers=tenant.headers,
    )
    assert response.status_code == 200, response.text
    assert TOKEN not in response.text and response.json()["secret_last4"] == "cdef"


async def context(tenant: Tenant, role: str) -> ToolContext:
    organization_id = uuid.UUID(tenant.org_id)
    async with tenant_scope(organization_id) as session:
        agent = await session.scalar(select(Agent).where(Agent.role_key == role))
        assert agent is not None
    return ToolContext(
        organization_id=organization_id,
        agent_id=agent.id,
        agent_role_key=role,
        objective_id=None,
        task_id=None,
        task_run_id=None,
        llm=MockLLMProvider(),
        embedding_model="local-hash-1536",
    )


async def test_read_tools_respect_the_allowlist(tenant: Tenant, github: FakeGitHub) -> None:
    await connect(tenant)
    architect = await context(tenant, "technical_architect")
    ok = await gateway.invoke(architect, "github_read_file", {"repo": REPO, "path": "README.md"})
    assert ok.status == "executed" and "ByteRoot" in ok.content
    other = await gateway.invoke(architect, "github_read_file", {"repo": "someone/else", "path": "README.md"})
    assert other.status == "error" and "allowlist" in other.content
    invalid = await gateway.invoke(architect, "github_read_file", {"repo": "../../etc", "path": "x"})
    assert invalid.status == "invalid"
    assert all("someone/else" not in path for _, path in github.requests)


async def test_unauthorized_agent_cannot_use_github(tenant: Tenant, github: FakeGitHub) -> None:
    await connect(tenant)
    copywriter = await context(tenant, "copywriter")
    denied = await gateway.invoke(copywriter, "github_read_file", {"repo": REPO, "path": "README.md"})
    assert denied.status == "denied"
    reviewer = await context(tenant, "reviewer")
    write = await gateway.invoke(reviewer, "github_create_branch", {"repo": REPO, "branch": "feature/x"})
    assert write.status == "denied"


async def test_engineer_works_on_a_branch_and_main_is_blocked(tenant: Tenant, github: FakeGitHub) -> None:
    await connect(tenant)
    engineer = await context(tenant, "fullstack_engineer")
    branch = await gateway.invoke(
        engineer, "github_create_branch", {"repo": REPO, "branch": "feature/landing"}
    )
    assert branch.status == "executed"
    commit = await gateway.invoke(
        engineer,
        "github_commit_changes",
        {
            "repo": REPO,
            "branch": "feature/landing",
            "files": {"index.html": "<h1>New</h1>"},
            "message": "Improve hero",
        },
    )
    assert commit.status == "executed" and commit.data["sha"] == "def4567890"
    for branch_name in ("main", "master", "MAIN"):
        blocked = await gateway.invoke(
            engineer,
            "github_write_file",
            {"repo": REPO, "branch": branch_name, "path": "a.txt", "content": "x", "message": "direct"},
        )
        assert blocked.status == "error" and "protected" in blocked.content
    assert ("PATCH", f"/repos/{REPO}/git/refs/heads/main") not in github.requests


async def test_write_actions_need_the_write_switch(tenant: Tenant, github: FakeGitHub) -> None:
    await connect(tenant, write=False)
    engineer = await context(tenant, "fullstack_engineer")
    outcome = await gateway.invoke(
        engineer, "github_create_branch", {"repo": REPO, "branch": "feature/landing"}
    )
    assert outcome.status == "error" and "disabled" in outcome.content


async def test_pull_request_and_merge_require_ceo_approval(tenant: Tenant, github: FakeGitHub) -> None:
    await connect(tenant)
    engineer = await context(tenant, "fullstack_engineer")
    pr = await gateway.invoke(
        engineer,
        "github_create_pull_request",
        {"repo": REPO, "head": "feature/landing", "title": "Improve site"},
    )
    assert pr.status == "approval_required"
    assert ("POST", f"/repos/{REPO}/pulls") not in github.requests
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        agent = await session.get(Agent, engineer.agent_id)
        assert agent is not None
        # Even an agent granted merge rights still needs the CEO for Level 3
        agent.tools.append(
            type(agent.tools[0])(organization_id=agent.organization_id, tool_key="github_merge_pull_request")
        )
    merge = await gateway.invoke(engineer, "github_merge_pull_request", {"repo": REPO, "number": 7})
    assert merge.status == "approval_required"


async def test_tenant_isolation_and_no_token_leak(
    tenant: Tenant, other_tenant: Tenant, github: FakeGitHub
) -> None:
    await connect(tenant)
    outsider = await context(other_tenant, "technical_architect")
    outcome = await gateway.invoke(outsider, "github_read_file", {"repo": REPO, "path": "README.md"})
    assert outcome.status == "error" and "not connected" in outcome.content
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        audits = (await session.scalars(select(AuditLog.details))).all()
    assert TOKEN not in json.dumps(audits, default=str)
    listing = await tenant.client.get(tenant.url("/integrations"))
    assert TOKEN not in listing.text


async def test_invalid_repo_names_are_rejected_at_configuration(tenant: Tenant) -> None:
    response = await tenant.client.put(
        tenant.url("/integrations/github"),
        json={"token": TOKEN, "allowed_repos": ["not a repo"], "write_enabled": False},
        headers=tenant.headers,
    )
    assert response.status_code == 400
