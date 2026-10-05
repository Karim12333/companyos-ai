import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from companyos.config import get_settings
from companyos.events import publish_pending

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@dataclass(frozen=True)
class TenantContext:
    organization_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    bypass_rls: bool = False


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, _transaction: Any, connection: Any) -> None:
    # Re-apply RLS context on every transaction so commits never drop it
    context: TenantContext | None = session.info.get("tenant_context")
    if context is None:
        return
    connection.execute(
        text(
            "SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :user, true), "
            "set_config('app.rls_bypass', :bypass, true)"
        ),
        {
            "org": str(context.organization_id) if context.organization_id else "",
            "user": str(context.user_id) if context.user_id else "",
            "bypass": "on" if context.bypass_rls else "off",
        },
    )


@asynccontextmanager
async def session_scope(context: TenantContext) -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        session.info["tenant_context"] = context
        async with session.begin():
            yield session
        await publish_pending(session.info.pop("realtime_events", []))


def tenant_scope(organization_id: uuid.UUID, user_id: uuid.UUID | None = None) -> Any:
    return session_scope(TenantContext(organization_id=organization_id, user_id=user_id))


def system_scope() -> Any:
    # Trusted system paths only (signup, platform admin, maintenance)
    return session_scope(TenantContext(bypass_rls=True))
