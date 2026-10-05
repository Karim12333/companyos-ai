import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.config import get_settings
from companyos.models import Integration, IntegrationCredential
from companyos.models.enums import IntegrationStatus
from companyos.providers.llm import LOCAL_EMBEDDING_MODEL, LLMProvider, OpenAICompatibleProvider
from companyos.providers.mock_llm import MOCK_MODEL, MockLLMProvider
from companyos.security import get_secret_box, mask_secret

DEFAULT_AI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


@dataclass
class ResolvedAI:
    provider: LLMProvider
    default_model: str
    premium_model: str
    embedding_model: str
    source: str


async def get_integration(
    session: AsyncSession, organization_id: uuid.UUID, provider_key: str
) -> Integration | None:
    return await session.scalar(
        select(Integration).where(
            Integration.organization_id == organization_id, Integration.provider_key == provider_key
        )
    )


async def get_integration_secret(session: AsyncSession, integration: Integration | None) -> str | None:
    if integration is None:
        return None
    credential = await session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.integration_id == integration.id,
            IntegrationCredential.organization_id == integration.organization_id,
        )
    )
    if credential is None:
        return None
    return get_secret_box().decrypt(credential.ciphertext)


async def store_integration_secret(
    session: AsyncSession, integration: Integration, secret: str, user_id: uuid.UUID | None
) -> None:
    ciphertext = get_secret_box().encrypt(secret)
    credential = await session.scalar(
        select(IntegrationCredential).where(IntegrationCredential.integration_id == integration.id)
    )
    if credential is None:
        session.add(
            IntegrationCredential(
                organization_id=integration.organization_id,
                integration_id=integration.id,
                ciphertext=ciphertext,
                secret_last4=mask_secret(secret),
                created_by_user_id=user_id,
            )
        )
    else:
        credential.ciphertext = ciphertext
        credential.secret_last4 = mask_secret(secret)
        credential.created_by_user_id = user_id
    integration.status = IntegrationStatus.CONNECTED
    await session.flush()


async def delete_integration_secret(session: AsyncSession, integration: Integration) -> None:
    credential = await session.scalar(
        select(IntegrationCredential).where(IntegrationCredential.integration_id == integration.id)
    )
    if credential is not None:
        await session.delete(credential)
    integration.status = IntegrationStatus.NOT_CONFIGURED
    await session.flush()


async def secret_last4(session: AsyncSession, integration: Integration) -> str | None:
    return await session.scalar(
        select(IntegrationCredential.secret_last4).where(
            IntegrationCredential.integration_id == integration.id
        )
    )


_llm_override: LLMProvider | None = None


def set_llm_override(provider: LLMProvider | None) -> None:
    global _llm_override
    _llm_override = provider


async def resolve_ai(session: AsyncSession, organization_id: uuid.UUID) -> ResolvedAI:
    """Organization key first, then (dev only) platform key, then the offline mock model."""
    if _llm_override is not None:
        return ResolvedAI(_llm_override, MOCK_MODEL, MOCK_MODEL, LOCAL_EMBEDDING_MODEL, "override")
    integration = await get_integration(session, organization_id, "ai_provider")
    if integration and integration.enabled:
        secret = await get_integration_secret(session, integration)
        if secret:
            config = integration.config or {}
            return ResolvedAI(
                provider=OpenAICompatibleProvider(
                    api_key=secret, base_url=config.get("base_url") or DEFAULT_AI_BASE_URL
                ),
                default_model=config.get("default_model") or "gpt-4o-mini",
                premium_model=config.get("premium_model") or config.get("default_model") or "gpt-4o",
                embedding_model=config.get("embedding_model") or DEFAULT_EMBEDDING_MODEL,
                source="organization",
            )
    settings = get_settings()
    platform_key = settings.platform_ai_api_key.get_secret_value()
    if settings.allow_platform_ai_fallback and platform_key and not settings.is_production:
        return ResolvedAI(
            provider=OpenAICompatibleProvider(api_key=platform_key, base_url=settings.platform_ai_base_url),
            default_model=settings.platform_ai_model,
            premium_model=settings.platform_ai_model,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
            source="platform",
        )
    return ResolvedAI(MockLLMProvider(), MOCK_MODEL, MOCK_MODEL, LOCAL_EMBEDDING_MODEL, "mock")
