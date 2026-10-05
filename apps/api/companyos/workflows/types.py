from dataclasses import dataclass, field

# Plain dataclasses only: this module is imported inside the deterministic workflow sandbox


@dataclass
class ObjectiveInput:
    organization_id: str
    objective_id: str
    resume: bool = False


@dataclass
class TaskRef:
    organization_id: str
    objective_id: str
    task_id: str


@dataclass
class ReadySnapshot:
    ready_task_ids: list[str]
    remaining: int
    max_parallel: int
    max_review_rounds: int


@dataclass
class ExecuteResult:
    status: str
    approval_ids: list[str] = field(default_factory=list)
    requires_review: bool = True
    escalation_ids: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    verdict: str
    feedback: str = ""
    escalation_id: str | None = None


@dataclass
class EscalationCheck:
    organization_id: str
    escalation_ids: list[str]


@dataclass
class EscalationRef:
    organization_id: str
    objective_id: str
    task_id: str
    escalation_id: str


@dataclass
class EscalationOutcome:
    # rerun: execute the task again; done: task finished; stopped: task failed or was cancelled
    action: str


@dataclass
class ApprovalResolution:
    # Approvals whose outcome is unknown and now wait for CEO verification
    escalation_ids: list[str] = field(default_factory=list)


@dataclass
class TaskFailure:
    organization_id: str
    objective_id: str
    task_id: str
    message: str


@dataclass
class ApprovalCheck:
    organization_id: str
    approval_ids: list[str]


@dataclass
class FinalizeInput:
    organization_id: str
    objective_id: str
    cancelled: bool = False
    planning_error: str | None = None
