import uuid
from typing import Any

from jinja2 import Environment, select_autoescape
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.config import get_settings
from companyos.models import Approval, Notification, Objective, Organization, OrganizationSettings
from companyos.models.enums import NotificationStatus, ObjectiveStatus
from companyos.observability import logger

_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))

LAYOUT = _env.from_string(
    """<!doctype html><html><body style="margin:0;background:#f5f6f8;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#111827">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 12px"><tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px">
<tr><td style="padding:20px 28px;border-bottom:1px solid #f0f1f3;font-weight:600;font-size:14px;letter-spacing:.02em">CompanyOS <span style="color:#6b7280;font-weight:400">· {{ organization }}</span></td></tr>
<tr><td style="padding:28px">
<div style="font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:{{ accent }}">{{ eyebrow }}</div>
<h1 style="font-size:20px;line-height:1.35;margin:8px 0 16px">{{ title }}</h1>
<p style="font-size:14px;line-height:1.6;color:#374151;margin:0 0 16px">{{ greeting }}</p>
{% if rows %}<table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;margin:0 0 16px">
{% for label, value in rows %}<tr><td style="padding:6px 0;color:#6b7280">{{ label }}</td><td style="padding:6px 0;text-align:right;font-weight:600">{{ value }}</td></tr>{% endfor %}
</table>{% endif %}
{% if body %}<p style="font-size:14px;line-height:1.6;color:#374151;margin:0 0 20px;white-space:pre-line">{{ body }}</p>{% endif %}
<a href="{{ link }}" style="display:inline-block;background:#111827;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;padding:10px 18px;border-radius:8px">{{ cta }}</a>
</td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid #f0f1f3;font-size:12px;color:#9ca3af">Internal notification. Agents never email external parties without your approval.</td></tr>
</table></td></tr></table></body></html>"""
)


def _text_version(context: dict[str, Any]) -> str:
    rows = "\n".join(f"{label}: {value}" for label, value in context.get("rows", []))
    return f"{context['title']}\n\n{context['greeting']}\n\n{rows}\n\n{context.get('body', '')}\n\n{context['cta']}: {context['link']}"


async def _recipients(session: AsyncSession, organization_id: uuid.UUID) -> tuple[list[str], str, str]:
    settings = await session.scalar(
        select(OrganizationSettings).where(OrganizationSettings.organization_id == organization_id)
    )
    organization = await session.get(Organization, organization_id)
    emails = list(settings.notification_emails) if settings else []
    ceo_name = (settings.ceo_name if settings else None) or "there"
    return emails, ceo_name, organization.slug if organization else ""


async def enqueue_notification(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    kind: str,
    dedupe_key: str,
    recipient: str,
    subject: str,
    context: dict[str, Any],
    objective_id: uuid.UUID | None = None,
) -> bool:
    """Writes the delivery intent in the caller's transaction; the DB unique key makes it idempotent."""
    result = await session.execute(
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            objective_id=objective_id,
            channel="email",
            kind=kind,
            recipient=recipient,
            subject=subject,
            status=NotificationStatus.PENDING.value,
            dedupe_key=f"{dedupe_key}:{recipient}",
            html_body=LAYOUT.render(**context),
            text_body=_text_version(context),
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Notification.id)
    )
    created = result.scalar() is not None
    if created:
        logger.info("notification_enqueued", kind=kind, organization_id=str(organization_id))
    return created


async def notify_objective_finished(
    session: AsyncSession, organization_id: uuid.UUID, objective_id: uuid.UUID
) -> None:
    objective = await session.get(Objective, objective_id)
    if objective is None or not objective.executive_summary:
        return
    emails, ceo_name, slug = await _recipients(session, organization_id)
    summary = objective.executive_summary
    narrative = summary.get("narrative", {})
    status = objective.status
    titles = {
        ObjectiveStatus.COMPLETED: ("Objective completed", "#047857"),
        ObjectiveStatus.COMPLETED_WITH_ISSUES: ("Objective completed with issues", "#b45309"),
        ObjectiveStatus.FAILED: ("Objective failed", "#b91c1c"),
        ObjectiveStatus.CANCELLED: ("Objective cancelled", "#6b7280"),
    }
    eyebrow, accent = titles.get(status, ("Objective update", "#374151"))
    organization = await session.get(Organization, organization_id)
    context = {
        "organization": organization.name if organization else "",
        "eyebrow": eyebrow,
        "accent": accent,
        "title": objective.title,
        "greeting": f"Hello {ceo_name}, your AI team finished working on this objective.",
        "rows": [
            ("Agents participated", summary.get("agents_involved", 0)),
            ("Tasks completed", f"{summary.get('tasks_completed', 0)} / {summary.get('tasks_total', 0)}"),
            ("Artifacts created", summary.get("artifacts_created", 0)),
            ("Issues detected and resolved", summary.get("issues_resolved", 0)),
            ("Failed tasks", summary.get("tasks_failed", 0)),
            ("Items awaiting your approval", summary.get("approvals_pending", 0)),
        ],
        "body": f"Executive recommendation: {narrative.get('recommendation', '')}",
        "cta": "Open executive report",
        "link": f"{get_settings().web_base_url}/{slug}/objectives/{objective.id}?tab=report",
    }
    for email in emails:
        await enqueue_notification(
            session,
            organization_id=organization_id,
            kind=f"objective_{status.value.lower()}",
            dedupe_key=f"objective:{objective.id}:{status.value}:{objective.completed_at}",
            recipient=email,
            subject=f"CompanyOS — {eyebrow}: {objective.title}",
            context=context,
            objective_id=objective.id,
        )


async def notify_approval_required(
    session: AsyncSession, organization_id: uuid.UUID, approval_id: uuid.UUID
) -> None:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        return
    emails, ceo_name, slug = await _recipients(session, organization_id)
    organization = await session.get(Organization, organization_id)
    context = {
        "organization": organization.name if organization else "",
        "eyebrow": "Approval required",
        "accent": "#b45309",
        "title": approval.title,
        "greeting": f"Hello {ceo_name}, an agent is waiting for your decision before taking this action.",
        "rows": [("Risk level", f"Level {approval.risk_level.value}"), ("Action", approval.action_key)],
        "body": approval.summary,
        "cta": "Review in CEO Inbox",
        "link": f"{get_settings().web_base_url}/{slug}/approvals/{approval.id}",
    }
    for email in emails:
        await enqueue_notification(
            session,
            organization_id=organization_id,
            kind="approval_required",
            dedupe_key=f"approval:{approval.id}",
            recipient=email,
            subject=f"CompanyOS — Approval required: {approval.title}",
            context=context,
            objective_id=approval.objective_id,
        )


async def notify_decision_required(
    session: AsyncSession, organization_id: uuid.UUID, escalation: Any
) -> None:
    emails, ceo_name, slug = await _recipients(session, organization_id)
    organization = await session.get(Organization, organization_id)
    context = {
        "organization": organization.name if organization else "",
        "eyebrow": "Decision required",
        "accent": "#3451d1",
        "title": escalation.question[:200],
        "greeting": f"Hello {ceo_name}, your team needs a decision before it can continue this work.",
        "rows": [("Type", escalation.kind.value.replace("_", " ").capitalize())],
        "body": escalation.context[:800],
        "cta": "Decide in CompanyOS",
        "link": f"{get_settings().web_base_url}/{slug}/escalations/{escalation.id}",
    }
    for email in emails:
        await enqueue_notification(
            session,
            organization_id=organization_id,
            kind="decision_required",
            dedupe_key=f"escalation:{escalation.id}",
            recipient=email,
            subject=f"CompanyOS — Decision required: {escalation.question[:80]}",
            context=context,
            objective_id=escalation.objective_id,
        )
