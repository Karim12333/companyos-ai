from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
import httpx

from companyos.config import get_settings


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    html: str
    text: str


@dataclass
class SendResult:
    provider: str
    message_id: str | None


class EmailProvider(Protocol):
    name: str

    async def send(self, email: OutgoingEmail) -> SendResult: ...


class SmtpEmailProvider:
    """Local development: delivers to Mailpit (http://localhost:8025)."""

    name = "smtp"

    async def send(self, email: OutgoingEmail) -> SendResult:
        settings = get_settings()
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        await aiosmtplib.send(message, hostname=settings.smtp_host, port=settings.smtp_port, timeout=15)
        return SendResult(provider=self.name, message_id=message.get("Message-ID"))


class ResendEmailProvider:
    name = "resend"

    async def send(self, email: OutgoingEmail) -> SendResult:
        settings = get_settings()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}"},
                json={
                    "from": settings.email_from,
                    "to": [email.to],
                    "subject": email.subject,
                    "html": email.html,
                    "text": email.text,
                },
            )
        response.raise_for_status()
        return SendResult(provider=self.name, message_id=response.json().get("id"))


class RecordingEmailProvider:
    """Test double that keeps sent emails in memory."""

    name = "recording"

    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []

    async def send(self, email: OutgoingEmail) -> SendResult:
        self.sent.append(email)
        return SendResult(provider=self.name, message_id=f"test-{len(self.sent)}")


_override: EmailProvider | None = None


def set_email_override(provider: EmailProvider | None) -> None:
    global _override
    _override = provider


def get_email_provider() -> EmailProvider:
    if _override:
        return _override
    if get_settings().email_provider == "resend":
        return ResendEmailProvider()
    return SmtpEmailProvider()
