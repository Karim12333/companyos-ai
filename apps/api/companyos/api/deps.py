import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.config import get_settings
from companyos.db import TenantContext, session_factory, system_scope
from companyos.events import get_redis, publish_pending
from companyos.models import OrganizationMember, User, UserSession
from companyos.models.enums import MemberRole
from companyos.observability import logger
from companyos.rbac import Permission, has_permission
from companyos.security import csrf_matches, hash_token

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class AuthContext:
    user: User
    session_token: str


@dataclass
class OrgContext:
    organization_id: uuid.UUID
    user: User
    role: MemberRole

    def require(self, permission: Permission) -> None:
        if not has_permission(self.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission.value}")


async def _session_for(context: TenantContext) -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        session.info["tenant_context"] = context
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        await publish_pending(session.info.pop("realtime_events", []))


async def system_session() -> AsyncIterator[AsyncSession]:
    # Used only by auth bootstrap and platform admin routes
    async for session in _session_for(TenantContext(bypass_rls=True)):
        yield session


async def get_auth(
    request: Request, session: Annotated[AsyncSession, Depends(system_session, scope="function")]
) -> AuthContext:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    row = await session.scalar(
        select(UserSession).where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        )
    )
    user = await session.get(User, row.user_id) if row else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    if request.method not in SAFE_METHODS and not csrf_matches(token, request.headers.get("X-CSRF-Token")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid CSRF token")
    request.state.user_id = str(user.id)
    return AuthContext(user=user, session_token=token)


async def get_org(
    organization_id: Annotated[uuid.UUID, Path(alias="org_id")],
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(system_session, scope="function")],
) -> OrgContext:
    membership = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == auth.user.id,
        )
    )
    if membership is None:
        # Same response for "missing" and "not yours" to avoid leaking tenant existence
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return OrgContext(organization_id=organization_id, user=auth.user, role=membership.role)


async def authorize_stream(request: Request, organization_id: uuid.UUID) -> None:
    # Short-lived check so long-lived streams never hold a DB connection
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    async with system_scope() as session:
        user_id = await session.scalar(
            select(UserSession.user_id).where(
                UserSession.token_hash == hash_token(token),
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > datetime.now(UTC),
            )
        )
        member = user_id and await session.scalar(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user_id
            )
        )
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")


async def org_session(org: Annotated[OrgContext, Depends(get_org)]) -> AsyncIterator[AsyncSession]:
    async for session in _session_for(
        TenantContext(organization_id=org.organization_id, user_id=org.user.id)
    ):
        yield session


def require(permission: Permission) -> Callable[[OrgContext], Awaitable[OrgContext]]:
    async def dependency(org: Annotated[OrgContext, Depends(get_org)]) -> OrgContext:
        org.require(permission)
        return org

    return dependency


async def require_platform_admin(auth: Annotated[AuthContext, Depends(get_auth)]) -> AuthContext:
    if not auth.user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform administrators only")
    return auth


async def rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    try:
        client = get_redis()
        bucket = f"ratelimit:{key}:{int(datetime.now(UTC).timestamp()) // window_seconds}"
        count = await client.incr(bucket)
        if count == 1:
            await client.expire(bucket, window_seconds)
    except Exception as error:
        # Fail open on Redis outage, but log it
        logger.warning("rate_limit_unavailable", error=str(error))
        return
    if count > limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, slow down")


Auth = Annotated[AuthContext, Depends(get_auth)]
Org = Annotated[OrgContext, Depends(get_org)]
OrgSession = Annotated[AsyncSession, Depends(org_session, scope="function")]
SystemSession = Annotated[AsyncSession, Depends(system_session, scope="function")]
