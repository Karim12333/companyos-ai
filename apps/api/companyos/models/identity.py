import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from companyos.models.base import Base, TenantMixin, str_enum
from companyos.models.enums import MemberRole


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))


class Organization(Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    template_key: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="active")
    plan: Mapped[str] = mapped_column(String(32), default="trial")
    billing_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)


class OrganizationMember(TenantMixin, Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_member_org_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[MemberRole] = mapped_column(str_enum(MemberRole), default=MemberRole.MEMBER)

    user: Mapped[User] = relationship(lazy="joined")


class OrganizationSettings(TenantMixin, Base):
    __tablename__ = "organization_settings"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_org_settings_org"),)

    default_model: Mapped[str] = mapped_column(String(120), default="gpt-4o-mini")
    premium_model: Mapped[str] = mapped_column(String(120), default="gpt-4o")
    max_task_iterations: Mapped[int] = mapped_column(Integer, default=8)
    max_parallel_tasks: Mapped[int] = mapped_column(Integer, default=4)
    max_review_revisions: Mapped[int] = mapped_column(Integer, default=2)
    max_messages_per_task: Mapped[int] = mapped_column(Integer, default=6)
    objective_budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("5"))
    daily_budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("20"))
    notification_emails: Mapped[list] = mapped_column(JSONB, default=list)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    ceo_name: Mapped[str | None] = mapped_column(String(120))
