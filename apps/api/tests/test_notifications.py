import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from companyos.db import system_scope, tenant_scope
from companyos.models import Notification
from companyos.models.enums import NotificationStatus
from companyos.providers.email import RecordingEmailProvider, set_email_override
from companyos.services import notification_dispatcher as dispatcher
from companyos.services.notifications import enqueue_notification
from tests.conftest import Tenant

CONTEXT = {
    "organization": "Acme",
    "eyebrow": "Test",
    "accent": "#000",
    "title": "Hello",
    "greeting": "Hi",
    "rows": [],
    "body": "",
    "cta": "Open",
    "link": "http://localhost",
}


@pytest.fixture
def provider(mailbox: RecordingEmailProvider) -> Iterator[RecordingEmailProvider]:
    fresh = RecordingEmailProvider()
    set_email_override(fresh)
    yield fresh
    set_email_override(mailbox)


async def enqueue(tenant: Tenant, key: str, recipient: str = "ceo@example.com") -> bool:
    async with tenant_scope(uuid.UUID(tenant.org_id)) as session:
        return await enqueue_notification(
            session,
            organization_id=uuid.UUID(tenant.org_id),
            kind="test",
            dedupe_key=key,
            recipient=recipient,
            subject="Subject",
            context=CONTEXT,
        )


async def row(key: str) -> Notification:
    async with system_scope() as session:
        notification = await session.scalar(
            select(Notification).where(Notification.dedupe_key == f"{key}:ceo@example.com")
        )
        assert notification is not None
        return notification


async def drain() -> None:
    while await dispatcher.dispatch_due():
        pass


async def test_enqueue_is_deduplicated_by_the_database(tenant: Tenant) -> None:
    key = f"dedupe:{uuid.uuid4()}"
    results = await asyncio.gather(*[enqueue(tenant, key) for _ in range(6)])
    assert results.count(True) == 1
    async with system_scope() as session:
        count = await session.scalar(
            select(func.count(Notification.id)).where(Notification.dedupe_key == f"{key}:ceo@example.com")
        )
    assert count == 1


async def test_parallel_dispatchers_send_each_notification_once(
    tenant: Tenant, provider: RecordingEmailProvider
) -> None:
    key = f"once:{uuid.uuid4()}"
    await enqueue(tenant, key)
    await asyncio.gather(dispatcher.dispatch_due(), dispatcher.dispatch_due(), dispatcher.dispatch_due())
    await drain()
    notification = await row(key)
    assert notification.status == NotificationStatus.SENT
    assert notification.attempts == 1
    assert provider.keys.count(notification.dedupe_key) == 1


async def test_transient_failures_retry_with_backoff_then_fail(
    tenant: Tenant, provider: RecordingEmailProvider
) -> None:
    key = f"retry:{uuid.uuid4()}"
    await enqueue(tenant, key)
    provider.fail_next = 1
    await drain()
    notification = await row(key)
    assert (notification.status, notification.attempts) == (NotificationStatus.PENDING, 1)
    assert notification.error and notification.next_attempt_at > datetime.now(UTC)

    async with system_scope() as session:
        await session.execute(
            update(Notification)
            .where(Notification.id == notification.id)
            .values(next_attempt_at=datetime.now(UTC))
        )
    await drain()
    sent = await row(key)
    assert (sent.status, sent.attempts) == (NotificationStatus.SENT, 2)

    exhausted_key = f"exhausted:{uuid.uuid4()}"
    await enqueue(tenant, exhausted_key)
    provider.fail_next = dispatcher.MAX_ATTEMPTS
    for _ in range(dispatcher.MAX_ATTEMPTS):
        async with system_scope() as session:
            await session.execute(
                update(Notification)
                .where(Notification.dedupe_key == f"{exhausted_key}:ceo@example.com")
                .values(next_attempt_at=datetime.now(UTC))
            )
        await drain()
    failed = await row(exhausted_key)
    assert (failed.status, failed.attempts) == (NotificationStatus.FAILED, dispatcher.MAX_ATTEMPTS)
    assert await dispatcher.retry_notification(failed.id)
    await drain()
    assert (await row(exhausted_key)).status == NotificationStatus.SENT


async def simulate_crash_while_sending(key: str) -> None:
    async with system_scope() as session:
        await session.execute(
            update(Notification)
            .where(Notification.dedupe_key == f"{key}:ceo@example.com")
            .values(
                status=NotificationStatus.SENDING,
                attempts=1,
                locked_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )


async def test_crash_mid_send_is_not_resent_without_provider_idempotency(
    tenant: Tenant, provider: RecordingEmailProvider
) -> None:
    key = f"stale:{uuid.uuid4()}"
    await enqueue(tenant, key)
    await simulate_crash_while_sending(key)
    await dispatcher.recover_stale()
    await drain()
    notification = await row(key)
    assert notification.status == NotificationStatus.FAILED
    assert "outcome unknown" in (notification.error or "")
    assert notification.dedupe_key not in provider.keys


async def test_crash_mid_send_is_resent_with_same_key_when_provider_deduplicates(
    tenant: Tenant, mailbox: RecordingEmailProvider
) -> None:
    idempotent = RecordingEmailProvider(supports_idempotency=True)
    set_email_override(idempotent)
    try:
        key = f"stale-idem:{uuid.uuid4()}"
        await enqueue(tenant, key)
        await simulate_crash_while_sending(key)
        await dispatcher.recover_stale()
        await drain()
        notification = await row(key)
        assert notification.status == NotificationStatus.SENT
        assert idempotent.keys.count(notification.dedupe_key) == 1
    finally:
        set_email_override(mailbox)
