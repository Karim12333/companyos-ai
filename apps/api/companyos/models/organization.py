import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from companyos.models.base import Base, TenantMixin, str_enum
from companyos.models.enums import AgentStatus, PermissionEffect


class Department(TenantMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_department_org_slug"),)

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    manager_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL", use_alter=True)
    )
    parent_department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Agent(TenantMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("organization_id", "role_key", name="uq_agent_org_role"),)

    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    manager_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    role_key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    system_instructions: Mapped[str] = mapped_column(Text, default="")
    goals: Mapped[list] = mapped_column(JSONB, default=list)
    responsibilities: Mapped[list] = mapped_column(JSONB, default=list)
    model: Mapped[str | None] = mapped_column(String(120))
    use_premium_model: Mapped[bool] = mapped_column(Boolean, default=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.4)
    max_iterations: Mapped[int] = mapped_column(Integer, default=6)
    status: Mapped[AgentStatus] = mapped_column(str_enum(AgentStatus), default=AgentStatus.IDLE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_coordinator: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    template_key: Mapped[str | None] = mapped_column(String(80))

    tools: Mapped[list["AgentTool"]] = relationship(lazy="selectin", cascade="all, delete-orphan")
    permissions: Mapped[list["AgentPermission"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class AgentRelationship(TenantMixin, Base):
    __tablename__ = "agent_relationships"
    __table_args__ = (UniqueConstraint("agent_id", "related_agent_id", "kind", name="uq_agent_relationship"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    related_agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32), default="can_delegate_to")


class AgentTool(TenantMixin, Base):
    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("agent_id", "tool_key", name="uq_agent_tool"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    tool_key: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class AgentPermission(TenantMixin, Base):
    __tablename__ = "agent_permissions"
    __table_args__ = (UniqueConstraint("agent_id", "action_key", name="uq_agent_permission"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    action_key: Mapped[str] = mapped_column(String(80))
    effect: Mapped[PermissionEffect] = mapped_column(str_enum(PermissionEffect))
