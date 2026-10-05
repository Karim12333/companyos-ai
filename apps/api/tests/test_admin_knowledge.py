import uuid
from typing import Any

import httpx
from sqlalchemy import select

from companyos.db import tenant_scope
from companyos.models import IntegrationCredential
from tests.conftest import Tenant

FAKE_KEY = "sk-test-1234567890abcdef"


async def test_ai_provider_key_is_encrypted_and_never_returned(tenant: Tenant) -> None:
    response = await tenant.client.put(
        tenant.url("/integrations/ai-provider"),
        json={"base_url": "https://api.example.com/v1", "default_model": "gpt-4o-mini", "api_key": FAKE_KEY},
        headers=tenant.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["has_secret"] is True
    assert body["secret_last4"] == "cdef"
    assert FAKE_KEY not in response.text
    listing = await tenant.client.get(tenant.url("/integrations"))
    assert FAKE_KEY not in listing.text
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        credential = await session.scalar(select(IntegrationCredential))
        assert credential is not None
        assert FAKE_KEY.encode() not in credential.ciphertext
    organization = (await tenant.client.get(tenant.url(""))).json()
    assert organization["ai"]["configured"] is True
    removed = await tenant.client.delete(
        tenant.url("/integrations/ai_provider/secret"), headers=tenant.headers
    )
    assert removed.json()["has_secret"] is False


async def test_settings_update_and_validation(tenant: Tenant) -> None:
    response = await tenant.client.patch(
        tenant.url("/settings"),
        json={"max_parallel_tasks": 6, "notification_emails": ["ops@example.com"]},
        headers=tenant.headers,
    )
    assert response.status_code == 200
    assert response.json()["max_parallel_tasks"] == 6
    invalid = await tenant.client.patch(
        tenant.url("/settings"), json={"max_parallel_tasks": 999}, headers=tenant.headers
    )
    assert invalid.status_code == 422


async def test_approval_policies_seeded_for_controlled_actions(tenant: Tenant) -> None:
    policies = (await tenant.client.get(tenant.url("/approval-policies"))).json()
    assert [policy["action_key"] for policy in policies] == ["schedule_social_post"]
    updated = await tenant.client.put(
        tenant.url(f"/approval-policies/{policies[0]['id']}"),
        json={"requires_approval": False},
        headers=tenant.headers,
    )
    assert updated.json()["requires_approval"] is False


async def test_knowledge_documents_are_indexed_and_searchable(tenant: Tenant) -> None:
    await tenant.client.post(
        tenant.url("/knowledge/memory"),
        json={"category": "brand", "title": "Voice", "content": "Technical and concise."},
        headers=tenant.headers,
    )
    document = await tenant.client.post(
        tenant.url("/knowledge/documents"),
        json={
            "title": "Pricing notes",
            "content": "Our pricing strategy targets SMB teams at 49 dollars per seat.",
        },
        headers=tenant.headers,
    )
    assert document.status_code == 201
    assert document.json()["chunk_count"] == 1
    results = (
        await tenant.client.get(tenant.url("/knowledge/search"), params={"q": "pricing strategy"})
    ).json()
    assert results["chunks"][0]["document_title"] == "Pricing notes"
    assert results["facts"][0]["title"] == "Voice"


async def test_upload_rejects_unsupported_files(tenant: Tenant) -> None:
    response = await tenant.client.post(
        tenant.url("/knowledge/documents/upload"),
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
        headers=tenant.headers,
    )
    assert response.status_code == 415


async def test_feedback_can_be_promoted_to_preference(tenant: Tenant) -> None:
    feedback = await tenant.client.post(
        tenant.url("/feedback"), json={"comment": "Too corporate. Be more technical."}, headers=tenant.headers
    )
    promoted = await tenant.client.post(
        tenant.url(f"/knowledge/feedback/{feedback.json()['id']}/promote"), json={}, headers=tenant.headers
    )
    assert promoted.status_code == 200
    preferences = (await tenant.client.get(tenant.url("/knowledge/preferences"))).json()
    assert preferences[0]["content"] == "Too corporate. Be more technical."


async def test_viewer_role_cannot_manage(app: Any, tenant: Tenant) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        email = f"viewer-{uuid.uuid4().hex[:6]}@example.com"
        signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": email,
                "password": "viewer-password",
                "full_name": "Viewer",
                "organization_name": "Own",
            },
        )
        added = await tenant.client.post(
            tenant.url("/members"), json={"email": email, "role": "viewer"}, headers=tenant.headers
        )
        assert added.status_code == 201
        headers = {"X-CSRF-Token": signup.json()["csrf_token"]}
        url = f"/api/v1/orgs/{tenant.org_id}"
        assert (await client.get(url + "/agents")).status_code == 200
        assert (
            await client.patch(url + "/settings", json={"max_parallel_tasks": 2}, headers=headers)
        ).status_code == 403
        objective = {"title": "Viewer objective", "instruction": "Viewers should not be able to do this."}
        assert (await client.post(url + "/objectives", json=objective, headers=headers)).status_code == 403
