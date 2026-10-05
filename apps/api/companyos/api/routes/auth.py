from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.api.deps import Auth, SystemSession, rate_limit
from companyos.api.schemas import (
    CreateOrganizationRequest,
    LoginRequest,
    MeResponse,
    OrganizationSummary,
    SignupRequest,
    UserOut,
)
from companyos.config import get_settings
from companyos.events import record_audit
from companyos.models import Organization, OrganizationMember, User, UserSession
from companyos.models.enums import ActorType
from companyos.security import csrf_token_for, hash_password, hash_token, new_session_token, verify_password
from companyos.services.organizations import create_organization
from companyos.templates import TEMPLATES

router = APIRouter(prefix="/auth", tags=["auth"])
org_router = APIRouter(prefix="/orgs", tags=["organizations"])

# Constant-time-ish defense: verify against a dummy hash when the user does not exist
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _organizations_for(session: AsyncSession, user: User) -> list[OrganizationSummary]:
    rows = await session.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(Organization.created_at)
    )
    return [
        OrganizationSummary(id=org.id, name=org.name, slug=org.slug, role=role.value)
        for org, role in rows.all()
    ]


async def _start_session(session: AsyncSession, response: Response, request: Request, user: User) -> str:
    settings = get_settings()
    token = new_session_token()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
            ip_address=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:400],
        )
    )
    user.last_login_at = datetime.now(UTC)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return token


async def _me(session: AsyncSession, user: User, token: str) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(user),
        csrf_token=csrf_token_for(token),
        organizations=await _organizations_for(session, user),
    )


@router.post("/signup", response_model=MeResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest, request: Request, response: Response, session: SystemSession
) -> MeResponse:
    await rate_limit(f"signup:{_client_ip(request)}", get_settings().signup_rate_limit_per_minute)
    email = body.email.lower()
    if await session.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    settings = get_settings()
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        password_hash=hash_password(body.password),
        is_platform_admin=email in [item.lower() for item in settings.platform_admin_emails],
    )
    session.add(user)
    await session.flush()
    organization = await create_organization(
        session,
        name=body.organization_name.strip(),
        owner_user_id=user.id,
        owner_email=email,
        ceo_name=body.full_name.split(" ")[0],
    )
    await record_audit(
        session,
        action="auth.signup",
        organization_id=organization.id,
        actor_type=ActorType.USER,
        actor_user_id=user.id,
        ip_address=_client_ip(request),
    )
    token = await _start_session(session, response, request, user)
    return await _me(session, user, token)


@router.post("/login", response_model=MeResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, session: SystemSession
) -> MeResponse:
    email = body.email.lower()
    limit = get_settings().login_rate_limit_per_minute
    await rate_limit(f"login:ip:{_client_ip(request)}", limit)
    await rate_limit(f"login:email:{email}", limit)
    user = await session.scalar(select(User).where(func.lower(User.email) == email))
    valid = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if user is None or not valid or not user.is_active:
        await record_audit(
            session,
            action="auth.login",
            organization_id=None,
            actor_type=ActorType.USER,
            actor_user_id=user.id if user else None,
            outcome="failure",
            ip_address=_client_ip(request),
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    await record_audit(
        session,
        action="auth.login",
        organization_id=None,
        actor_type=ActorType.USER,
        actor_user_id=user.id,
        ip_address=_client_ip(request),
    )
    token = await _start_session(session, response, request, user)
    return await _me(session, user, token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(auth: Auth, response: Response, session: SystemSession) -> None:
    row = await session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(auth.session_token))
    )
    if row is not None:
        row.revoked_at = datetime.now(UTC)
    response.delete_cookie(get_settings().session_cookie_name, path="/")


@router.get("/me", response_model=MeResponse)
async def me(auth: Auth, session: SystemSession) -> MeResponse:
    return await _me(session, auth.user, auth.session_token)


@org_router.post("", response_model=OrganizationSummary, status_code=status.HTTP_201_CREATED)
async def create_org(
    body: CreateOrganizationRequest, auth: Auth, session: SystemSession
) -> OrganizationSummary:
    if body.template_key not in TEMPLATES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown organization template")
    organization = await create_organization(
        session,
        name=body.name.strip(),
        owner_user_id=auth.user.id,
        owner_email=auth.user.email,
        template_key=body.template_key,
        ceo_name=auth.user.full_name.split(" ")[0],
    )
    await record_audit(
        session,
        action="organization.create",
        organization_id=organization.id,
        actor_type=ActorType.USER,
        actor_user_id=auth.user.id,
    )
    return OrganizationSummary(
        id=organization.id, name=organization.name, slug=organization.slug, role="owner"
    )


@org_router.get("/templates")
async def list_templates(auth: Auth) -> list[dict[str, str]]:
    return [{"key": t.key, "name": t.name, "description": t.description} for t in TEMPLATES.values()]
