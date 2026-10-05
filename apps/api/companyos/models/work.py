import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from companyos.models.base import Base, TenantMixin, str_enum
from companyos.models.enums import (
    ActorType,
    ErrorCategory,
    MessageKind,
    ObjectiveStatus,
    Priority,
    TaskStatus,
)


class Project(TenantMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    start_date: Mapped[date | None] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date)
    milestones: Mapped[list] = mapped_column(JSONB, default=list)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Objective(TenantMixin, Base):
    __tablename__ = "objectives"
    __table_args__ = (Index("ix_objectives_org_status", "organization_id", "status"),)

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    coordinator_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300))
    instruction: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ObjectiveStatus] = mapped_column(str_enum(ObjectiveStatus), default=ObjectiveStatus.DRAFT)
    priority: Mapped[Priority] = mapped_column(str_enum(Priority), default=Priority.NORMAL)
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_stage: Mapped[str] = mapped_column(String(120), default="Draft")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    workflow_id: Mapped[str | None] = mapped_column(String(200))
    budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    approval_policy: Mapped[dict] = mapped_column(JSONB, default=dict)
    plan_summary: Mapped[str] = mapped_column(Text, default="")
    executive_summary: Mapped[dict | None] = mapped_column(JSONB)
    issues: Mapped[list] = mapped_column(JSONB, default=list)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(TenantMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("objective_id", "plan_key", name="uq_task_objective_plan_key"),
        Index("ix_tasks_objective_status", "objective_id", "status"),
    )

    objective_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("objectives.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    plan_key: Mapped[str] = mapped_column(String(80))
    role_key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    instructions: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[Priority] = mapped_column(str_enum(Priority), default=Priority.NORMAL)
    status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus), default=TaskStatus.QUEUED)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    expected_output_type: Mapped[str] = mapped_column(String(80), default="document")
    acceptance_criteria: Mapped[list] = mapped_column(JSONB, default=list)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    output_summary: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict | None] = mapped_column(JSONB)
    review_feedback: Mapped[str] = mapped_column(Text, default="")
    error_category: Mapped[ErrorCategory | None] = mapped_column(str_enum(ErrorCategory))
    error_message: Mapped[str | None] = mapped_column(Text)
    recoverable: Mapped[bool | None] = mapped_column(Boolean)
    execution_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)


class TaskDependency(TenantMixin, Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),)

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )


class TaskRun(TenantMixin, Base):
    __tablename__ = "task_runs"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="execute")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    trace: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class WorkflowRun(TenantMixin, Base):
    __tablename__ = "workflow_runs"

    objective_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("objectives.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[str] = mapped_column(String(200))
    run_id: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="objective")
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class AgentMessage(TenantMixin, Base):
    __tablename__ = "agent_messages"

    objective_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objectives.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    sender_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    recipient_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    kind: Mapped[MessageKind] = mapped_column(str_enum(MessageKind), default=MessageKind.INFO)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="")


class ActivityEvent(TenantMixin, Base):
    __tablename__ = "activity_events"
    __table_args__ = (Index("ix_activity_org_created", "organization_id", "created_at"),)

    objective_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("objectives.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    actor_type: Mapped[ActorType] = mapped_column(str_enum(ActorType), default=ActorType.SYSTEM)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
