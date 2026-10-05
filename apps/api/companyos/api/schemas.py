import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from companyos.models.enums import Priority
from companyos.security import MIN_PASSWORD_LENGTH


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=2, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class OrganizationSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    is_platform_admin: bool


class MeResponse(BaseModel):
    user: UserOut
    csrf_token: str
    organizations: list[OrganizationSummary]


class CreateOrganizationRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    template_key: str = "software_ai_company"


# ---------- organization structure ----------


class DepartmentOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    manager_agent_id: uuid.UUID | None
    sort_order: int


class AgentOut(ORM):
    id: uuid.UUID
    name: str
    role_key: str
    title: str
    description: str
    department_id: uuid.UUID | None
    manager_agent_id: uuid.UUID | None
    status: str
    is_active: bool
    is_coordinator: bool
    model: str | None
    use_premium_model: bool


class AgentDetailOut(AgentOut):
    system_instructions: str
    goals: list[str]
    responsibilities: list[str]
    temperature: float
    max_iterations: int
    memory_config: dict[str, Any]


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    system_instructions: str | None = Field(default=None, max_length=20000)
    goals: list[str] | None = None
    responsibilities: list[str] | None = None
    model: str | None = Field(default=None, max_length=120)
    use_premium_model: bool | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_iterations: int | None = Field(default=None, ge=1, le=20)
    is_active: bool | None = None
    department_id: uuid.UUID | None = None
    manager_agent_id: uuid.UUID | None = None
    tool_keys: list[str] | None = None
    delegate_role_keys: list[str] | None = None


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    title: str = Field(min_length=2, max_length=120)
    department_id: uuid.UUID
    manager_agent_id: uuid.UUID | None = None
    description: str = Field(default="", max_length=4000)
    system_instructions: str = Field(min_length=10, max_length=20000)
    goals: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    tool_keys: list[str] = Field(default_factory=lambda: ["search_company_knowledge", "create_artifact"])


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)


# ---------- work ----------


class ObjectiveCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    instruction: str = Field(min_length=10, max_length=20000)
    context: str = Field(default="", max_length=20000)
    priority: Priority = Priority.NORMAL
    project_id: uuid.UUID | None = None
    target_date: datetime | None = None
    budget_usd: Decimal | None = Field(default=None, ge=0, le=10000)
    external_actions: Literal["require_approval", "deny"] = "require_approval"


class ObjectiveOut(ORM):
    id: uuid.UUID
    title: str
    instruction: str
    context: str
    status: str
    priority: str
    progress: int
    current_stage: str
    project_id: uuid.UUID | None
    coordinator_agent_id: uuid.UUID | None
    workflow_id: str | None
    target_date: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    budget_usd: Decimal | None
    cost_usd: Decimal
    approval_policy: dict[str, Any]
    plan_summary: str
    is_paused: bool
    issues: list[Any]


class ObjectiveDetailOut(ObjectiveOut):
    executive_summary: dict[str, Any] | None


class TaskOut(ORM):
    id: uuid.UUID
    objective_id: uuid.UUID
    parent_task_id: uuid.UUID | None
    assigned_agent_id: uuid.UUID | None
    department_id: uuid.UUID | None
    plan_key: str
    role_key: str
    title: str
    instructions: str
    priority: str
    status: str
    sequence: int
    started_at: datetime | None
    completed_at: datetime | None
    retry_count: int
    max_retries: int
    revision_count: int
    expected_output_type: str
    acceptance_criteria: list[str]
    requires_review: bool
    output_summary: str
    review_feedback: str
    error_category: str | None
    error_message: str | None
    recoverable: bool | None
    result: dict[str, Any] | None
    execution_metadata: dict[str, Any]
    depends_on: list[uuid.UUID] = Field(default_factory=list)


class MessageOut(ORM):
    id: uuid.UUID
    objective_id: uuid.UUID | None
    task_id: uuid.UUID | None
    sender_agent_id: uuid.UUID | None
    recipient_agent_id: uuid.UUID | None
    kind: str
    subject: str
    body: str
    reason: str
    created_at: datetime


class ActivityOut(ORM):
    id: uuid.UUID
    event_type: str
    summary: str
    objective_id: uuid.UUID | None
    project_id: uuid.UUID | None
    department_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    task_id: uuid.UUID | None
    actor_type: str
    data: dict[str, Any]
    created_at: datetime


class ArtifactOut(ORM):
    id: uuid.UUID
    title: str
    filename: str
    kind: str
    mime_type: str
    current_version: int
    review_status: str
    approval_status: str
    objective_id: uuid.UUID | None
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    generated_by_mock: bool
    created_at: datetime
    updated_at: datetime


class ArtifactVersionOut(ORM):
    id: uuid.UUID
    version: int
    size_bytes: int
    checksum_sha256: str
    preview_text: str
    change_note: str
    created_by_agent_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime


class ApprovalOut(ORM):
    id: uuid.UUID
    objective_id: uuid.UUID | None
    task_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    artifact_id: uuid.UUID | None
    action_key: str
    risk_level: str
    title: str
    summary: str
    payload: dict[str, Any]
    status: str
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str
    executed_at: datetime | None
    execution_result: dict[str, Any] | None
    created_at: datetime


class ApprovalDecision(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=2000)


class InboxItemOut(ORM):
    id: uuid.UUID
    category: str
    severity: str
    objective_id: uuid.UUID | None
    department_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    task_id: uuid.UUID | None
    approval_id: uuid.UUID | None
    artifact_id: uuid.UUID | None
    title: str
    summary: str
    is_read: bool
    action_required: bool
    resolved_at: datetime | None
    link: str | None
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=5000)
    start_date: date | None = None
    target_date: date | None = None
    milestones: list[dict[str, Any]] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: Literal["active", "on_hold", "completed", "archived"] | None = None
    start_date: date | None = None
    target_date: date | None = None
    milestones: list[dict[str, Any]] | None = None


class ProjectOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    status: str
    start_date: date | None
    target_date: date | None
    milestones: list[Any]
    created_at: datetime


# ---------- knowledge ----------


class MemoryCreate(BaseModel):
    category: Literal["identity", "mission", "brand", "policy", "product", "business_rule"]
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=2, max_length=10000)


class MemoryOut(ORM):
    id: uuid.UUID
    category: str
    title: str
    content: str
    is_active: bool
    created_at: datetime


class DocumentCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    content: str = Field(min_length=10, max_length=500_000)
    project_id: uuid.UUID | None = None
    trusted: bool = False


class DocumentOut(ORM):
    id: uuid.UUID
    title: str
    source: str
    mime_type: str
    chunk_count: int
    is_untrusted: bool
    project_id: uuid.UUID | None
    created_at: datetime


class FeedbackCreate(BaseModel):
    comment: str = Field(min_length=2, max_length=4000)
    rating: int | None = Field(default=None, ge=1, le=5)
    artifact_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    objective_id: uuid.UUID | None = None


class FeedbackOut(ORM):
    id: uuid.UUID
    comment: str
    rating: int | None
    status: str
    artifact_id: uuid.UUID | None
    task_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    objective_id: uuid.UUID | None
    created_at: datetime


class PromoteFeedback(BaseModel):
    scope: Literal["organization", "agent"] = "organization"
    content: str | None = Field(default=None, max_length=4000)


class PreferenceCreate(BaseModel):
    content: str = Field(min_length=3, max_length=4000)
    scope: Literal["organization", "agent"] = "organization"
    agent_id: uuid.UUID | None = None


class PreferenceOut(ORM):
    id: uuid.UUID
    scope: str
    agent_id: uuid.UUID | None
    content: str
    is_active: bool
    source_feedback_id: uuid.UUID | None
    created_at: datetime


# ---------- settings & integrations ----------


class SettingsOut(ORM):
    default_model: str
    premium_model: str
    max_task_iterations: int
    max_parallel_tasks: int
    max_review_revisions: int
    max_messages_per_task: int
    objective_budget_usd: Decimal
    daily_budget_usd: Decimal
    notification_emails: list[str]
    timezone: str
    ceo_name: str | None


class SettingsUpdate(BaseModel):
    max_task_iterations: int | None = Field(default=None, ge=1, le=20)
    max_parallel_tasks: int | None = Field(default=None, ge=1, le=16)
    max_review_revisions: int | None = Field(default=None, ge=0, le=5)
    max_messages_per_task: int | None = Field(default=None, ge=0, le=20)
    objective_budget_usd: Decimal | None = Field(default=None, ge=0, le=10000)
    daily_budget_usd: Decimal | None = Field(default=None, ge=0, le=100000)
    notification_emails: list[EmailStr] | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    ceo_name: str | None = Field(default=None, max_length=120)


class ApprovalPolicyOut(ORM):
    id: uuid.UUID
    action_key: str
    requires_approval: bool
    description: str


class ApprovalPolicyUpdate(BaseModel):
    requires_approval: bool


class IntegrationOut(BaseModel):
    id: uuid.UUID
    provider_key: str
    name: str
    enabled: bool
    status: str
    scopes: list[str]
    config: dict[str, Any]
    has_secret: bool
    secret_last4: str | None
    health_message: str | None
    last_checked_at: datetime | None


class AIProviderUpdate(BaseModel):
    base_url: str = Field(default="https://api.openai.com/v1", max_length=300, pattern=r"^https?://")
    default_model: str = Field(default="gpt-4o-mini", max_length=120)
    premium_model: str = Field(default="gpt-4o", max_length=120)
    embedding_model: str = Field(default="text-embedding-3-small", max_length=120)
    api_key: str | None = Field(default=None, min_length=8, max_length=500)
    enabled: bool = True


class SecretUpdate(BaseModel):
    api_key: str = Field(min_length=8, max_length=500)


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    created_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: Literal["admin", "member", "viewer"] = "member"
