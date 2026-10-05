import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from companyos.models.base import Base, TenantMixin, str_enum
from companyos.models.enums import (
    ApprovalStatus,
    ArtifactApprovalStatus,
    FeedbackStatus,
    InboxCategory,
    NotificationStatus,
    ReviewStatus,
    RiskLevel,
    Severity,
)


class Artifact(TenantMixin, Base):
    __tablename__ = "artifacts"

    objective_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objectives.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(64), default="document")
    mime_type: Mapped[str] = mapped_column(String(120), default="text/markdown")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    review_status: Mapped[ReviewStatus] = mapped_column(str_enum(ReviewStatus), default=ReviewStatus.PENDING)
    approval_status: Mapped[ArtifactApprovalStatus] = mapped_column(
        str_enum(ArtifactApprovalStatus), default=ArtifactApprovalStatus.NONE
    )
    generated_by_mock: Mapped[bool] = mapped_column(Boolean, default=False)


class ArtifactVersion(TenantMixin, Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),)

    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    preview_text: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class Approval(TenantMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_org_status", "organization_id", "status"),)

    objective_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objectives.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    action_key: Mapped[str] = mapped_column(String(80))
    tool_key: Mapped[str | None] = mapped_column(String(80))
    risk_level: Mapped[RiskLevel] = mapped_column(str_enum(RiskLevel, 4))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[ApprovalStatus] = mapped_column(str_enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str] = mapped_column(Text, default="")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_result: Mapped[dict | None] = mapped_column(JSONB)


class ApprovalPolicy(TenantMixin, Base):
    __tablename__ = "approval_policies"
    __table_args__ = (UniqueConstraint("organization_id", "action_key", name="uq_approval_policy_action"),)

    action_key: Mapped[str] = mapped_column(String(80))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text, default="")


class InboxItem(TenantMixin, Base):
    __tablename__ = "inbox_items"
    __table_args__ = (Index("ix_inbox_org_read", "organization_id", "is_read"),)

    category: Mapped[InboxCategory] = mapped_column(str_enum(InboxCategory))
    severity: Mapped[Severity] = mapped_column(str_enum(Severity), default=Severity.INFO)
    objective_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("objectives.id", ondelete="CASCADE"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id", ondelete="CASCADE"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    action_required: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    link: Mapped[str | None] = mapped_column(String(500))


class Notification(TenantMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    objective_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("objectives.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(32), default="email")
    kind: Mapped[str] = mapped_column(String(64))
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300))
    status: Mapped[NotificationStatus] = mapped_column(
        str_enum(NotificationStatus), default=NotificationStatus.PENDING
    )
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)


class AgentFeedback(TenantMixin, Base):
    __tablename__ = "agent_feedback"

    objective_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("objectives.id", ondelete="SET NULL"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text)
    status: Mapped[FeedbackStatus] = mapped_column(str_enum(FeedbackStatus), default=FeedbackStatus.OPEN)


class OrganizationPreference(TenantMixin, Base):
    __tablename__ = "organization_preferences"

    scope: Mapped[str] = mapped_column(String(32), default="organization")
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    source_feedback_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_feedback.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
