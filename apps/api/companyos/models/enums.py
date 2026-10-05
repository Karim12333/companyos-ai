from enum import StrEnum


class MemberRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    PAUSED = "paused"


class ObjectiveStatus(StrEnum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    REVIEWING = "REVIEWING"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ISSUES = "COMPLETED_WITH_ISSUES"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


OBJECTIVE_TERMINAL = {
    ObjectiveStatus.COMPLETED,
    ObjectiveStatus.COMPLETED_WITH_ISSUES,
    ObjectiveStatus.FAILED,
    ObjectiveStatus.CANCELLED,
}


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    REVIEW = "REVIEW"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TASK_TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ErrorCategory(StrEnum):
    PROVIDER = "provider"
    TOOL = "tool"
    POLICY = "policy"
    BUDGET = "budget"
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    DEPENDENCY = "dependency"
    REVIEW_EXHAUSTED = "review_exhausted"
    ESCALATION = "escalation"
    EXTERNAL_ACTION = "external_action"
    INTERNAL = "internal"


class RiskLevel(StrEnum):
    AUTONOMOUS = "1"
    CONTROLLED = "2"
    HUMAN_APPROVAL = "3"


class PermissionEffect(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CHANGES_REQUESTED = "changes_requested"
    ACCEPTED = "accepted"


class ArtifactApprovalStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class InboxCategory(StrEnum):
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DECISION_REQUIRED = "DECISION_REQUIRED"
    REVIEW_RECOMMENDED = "REVIEW_RECOMMENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INFO = "INFO"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MessageKind(StrEnum):
    HANDOFF = "handoff"
    REQUEST = "request"
    FEEDBACK = "feedback"
    DELEGATION = "delegation"
    INFO = "info"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class FeedbackStatus(StrEnum):
    OPEN = "open"
    PROMOTED = "promoted"
    DISMISSED = "dismissed"


class MemoryCategory(StrEnum):
    IDENTITY = "identity"
    MISSION = "mission"
    BRAND = "brand"
    POLICY = "policy"
    PRODUCT = "product"
    BUSINESS_RULE = "business_rule"


class IntegrationStatus(StrEnum):
    CONNECTED = "connected"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"
    DISABLED = "disabled"


class EscalationStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class EscalationKind(StrEnum):
    REVIEW_EXHAUSTED = "review_exhausted"
    DECISION_REQUIRED = "decision_required"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    AMBIGUOUS_SCOPE = "ambiguous_scope"
    ACTION_OUTCOME_UNKNOWN = "action_outcome_unknown"
