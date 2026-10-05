"""Delivers outbox notifications: claim with SKIP LOCKED, send outside the transaction, record the result."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update

from companyos.db import system_scope
from companyos.models import Notification
from companyos.models.enums import NotificationStatus
from companyos.observability import logger
from companyos.providers.email import OutgoingEmail, get_email_provider

MAX_ATTEMPTS = 5
BATCH_SIZE = 20
POLL_SECONDS = 3
# A row left in "sending" this long belongs to a dispatcher that died mid-send
STALE_SENDING = timedelta(minutes=10)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(30 * 2 ** (attempts - 1), 3600))


async def recover_stale() -> int:
    """Rows stuck in sending: re-send only when the provider deduplicates, otherwise surface them."""
    provider = get_email_provider()
    async with system_scope() as session:
        stale = (
            await session.scalars(
                select(Notification)
                .where(
                    Notification.status == NotificationStatus.SENDING,
                    Notification.locked_at < datetime.now(UTC) - STALE_SENDING,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in stale:
            row.locked_at = None
            if provider.supports_idempotency:
                row.status = NotificationStatus.PENDING
                row.next_attempt_at = datetime.now(UTC)
            else:
                row.status = NotificationStatus.FAILED
                row.error = "Delivery outcome unknown: the dispatcher stopped while sending. Retry manually."
        return len(stale)


async def _claim(limit: int) -> list[uuid.UUID]:
    async with system_scope() as session:
        rows = await session.execute(
            text(
                "UPDATE notifications SET status = 'sending', attempts = attempts + 1, locked_at = now() "
                "WHERE id IN (SELECT id FROM notifications WHERE status = 'pending' AND next_attempt_at <= now() "
                "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT :limit) RETURNING id"
            ),
            {"limit": limit},
        )
        return [row[0] for row in rows.all()]


async def _deliver(notification_id: uuid.UUID) -> None:
    async with system_scope() as session:
        row = await session.get(Notification, notification_id)
        assert row is not None
        email = OutgoingEmail(to=row.recipient, subject=row.subject, html=row.html_body, text=row.text_body)
        key, attempts = row.dedupe_key, row.attempts
    provider = get_email_provider()
    try:
        result = await provider.send(email, idempotency_key=key)
    except Exception as error:
        logger.warning("notification_send_failed", notification_id=str(notification_id), error=str(error))
        final = attempts >= MAX_ATTEMPTS
        async with system_scope() as session:
            await session.execute(
                update(Notification)
                .where(Notification.id == notification_id)
                .values(
                    status=NotificationStatus.FAILED if final else NotificationStatus.PENDING,
                    error=str(error)[:1000],
                    provider=provider.name,
                    locked_at=None,
                    next_attempt_at=datetime.now(UTC) + backoff(attempts),
                )
            )
        return
    async with system_scope() as session:
        await session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(
                status=NotificationStatus.SENT,
                provider=result.provider,
                provider_message_id=result.message_id,
                sent_at=datetime.now(UTC),
                error=None,
                locked_at=None,
            )
        )


async def dispatch_due(limit: int = BATCH_SIZE) -> int:
    claimed = await _claim(limit)
    for notification_id in claimed:
        await _deliver(notification_id)
    return len(claimed)


async def retry_notification(notification_id: uuid.UUID) -> bool:
    async with system_scope() as session:
        result = await session.execute(
            update(Notification)
            .where(Notification.id == notification_id, Notification.status == NotificationStatus.FAILED)
            .values(status=NotificationStatus.PENDING, next_attempt_at=datetime.now(UTC), error=None)
            .returning(Notification.id)
        )
        return result.scalar() is not None


async def run_dispatcher(stop: asyncio.Event) -> None:
    logger.info("notification_dispatcher_started")
    while not stop.is_set():
        try:
            await recover_stale()
            while await dispatch_due():
                pass
        except Exception as error:
            # Keep the loop alive; failures are visible per notification and in logs
            logger.error("notification_dispatcher_error", error=str(error))
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            continue
