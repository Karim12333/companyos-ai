export type UUID = string;

export interface OrganizationSummary {
  id: UUID;
  name: string;
  slug: string;
  role: "owner" | "admin" | "member" | "viewer";
}

export interface User {
  id: UUID;
  email: string;
  full_name: string;
  is_platform_admin: boolean;
}

export interface Me {
  user: User;
  csrf_token: string;
  organizations: OrganizationSummary[];
}

export interface Department {
  id: UUID;
  name: string;
  slug: string;
  description: string;
  manager_agent_id: UUID | null;
  sort_order: number;
  agent_count?: number;
  active_tasks?: number;
  completed_tasks?: number;
  manager_name?: string | null;
  status?: "active" | "idle" | "completed_today";
}

export interface Agent {
  id: UUID;
  name: string;
  role_key: string;
  title: string;
  description: string;
  department_id: UUID | null;
  manager_agent_id: UUID | null;
  status: "idle" | "working" | "paused";
  is_active: boolean;
  is_coordinator: boolean;
  model: string | null;
  use_premium_model: boolean;
}

export interface AgentDetail extends Agent {
  system_instructions: string;
  goals: string[];
  responsibilities: string[];
  temperature: number;
  max_iterations: number;
}

export type ObjectiveStatus =
  | "DRAFT"
  | "PLANNING"
  | "RUNNING"
  | "WAITING"
  | "WAITING_FOR_APPROVAL"
  | "REVIEWING"
  | "PAUSED"
  | "COMPLETED"
  | "COMPLETED_WITH_ISSUES"
  | "FAILED"
  | "CANCELLED";

export interface ExecutiveSummary {
  objective_title: string;
  status: ObjectiveStatus;
  duration_seconds: number;
  departments: string[];
  agents_involved: number;
  agent_names: string[];
  tasks_total: number;
  tasks_completed: number;
  tasks_failed: number;
  completed_titles: string[];
  failed_titles: string[];
  failures: { task: string; category: string | null; message: string; recoverable: boolean | null }[];
  revisions_requested: number;
  issues_resolved: number;
  artifacts_created: number;
  approvals_total: number;
  approvals_pending: number;
  approvals_approved: number;
  approvals_rejected: number;
  cost_usd: number;
  report_artifact_id?: UUID;
  narrative: {
    headline: string;
    overall_assessment: string;
    key_findings: string[];
    recommendation: string;
    next_actions: string[];
    risks: string[];
  };
}

export interface Objective {
  id: UUID;
  title: string;
  instruction: string;
  context: string;
  status: ObjectiveStatus;
  priority: "low" | "normal" | "high" | "urgent";
  progress: number;
  current_stage: string;
  project_id: UUID | null;
  coordinator_agent_id: UUID | null;
  workflow_id: string | null;
  target_date: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  budget_usd: string | null;
  cost_usd: string;
  approval_policy: { external_actions?: "require_approval" | "deny" };
  plan_summary: string;
  is_paused: boolean;
  issues: { type: string; message: string }[];
  executive_summary?: ExecutiveSummary | null;
}

export type TaskStatus =
  | "QUEUED"
  | "READY"
  | "RUNNING"
  | "BLOCKED"
  | "REVIEW"
  | "WAITING_FOR_APPROVAL"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface Task {
  id: UUID;
  objective_id: UUID;
  parent_task_id: UUID | null;
  assigned_agent_id: UUID | null;
  department_id: UUID | null;
  plan_key: string;
  role_key: string;
  title: string;
  instructions: string;
  priority: string;
  status: TaskStatus;
  sequence: number;
  started_at: string | null;
  completed_at: string | null;
  retry_count: number;
  max_retries: number;
  revision_count: number;
  expected_output_type: string;
  acceptance_criteria: string[];
  requires_review: boolean;
  output_summary: string;
  review_feedback: string;
  error_category: string | null;
  error_message: string | null;
  recoverable: boolean | null;
  result: { artifact_ids?: UUID[]; approval_ids?: UUID[] } | null;
  execution_metadata: Record<string, unknown>;
  depends_on: UUID[];
}

export interface AgentMessage {
  id: UUID;
  objective_id: UUID | null;
  task_id: UUID | null;
  sender_agent_id: UUID | null;
  recipient_agent_id: UUID | null;
  kind: "handoff" | "request" | "feedback" | "delegation" | "info";
  subject: string;
  body: string;
  reason: string;
  created_at: string;
}

export interface ActivityEvent {
  id: UUID;
  event_type: string;
  summary: string;
  objective_id: UUID | null;
  project_id: UUID | null;
  department_id: UUID | null;
  agent_id: UUID | null;
  task_id: UUID | null;
  actor_type: "user" | "agent" | "system";
  data: Record<string, unknown>;
  created_at: string;
}

export interface Artifact {
  id: UUID;
  title: string;
  filename: string;
  kind: string;
  mime_type: string;
  current_version: number;
  review_status: "not_required" | "pending" | "changes_requested" | "accepted";
  approval_status: "none" | "pending" | "approved" | "rejected";
  objective_id: UUID | null;
  project_id: UUID | null;
  task_id: UUID | null;
  agent_id: UUID | null;
  generated_by_mock: boolean;
  created_at: string;
  updated_at: string;
}

export interface ArtifactVersion {
  id: UUID;
  version: number;
  size_bytes: number;
  checksum_sha256: string;
  preview_text: string;
  change_note: string;
  created_by_agent_id: UUID | null;
  created_at: string;
}

export interface Approval {
  id: UUID;
  objective_id: UUID | null;
  task_id: UUID | null;
  agent_id: UUID | null;
  artifact_id: UUID | null;
  action_key: string;
  risk_level: "1" | "2" | "3";
  title: string;
  summary: string;
  payload: { arguments?: Record<string, unknown>; reason?: string };
  status: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "CANCELLED";
  decided_at: string | null;
  decision_note: string;
  executed_at: string | null;
  execution_result: { status?: string; message?: string } | null;
  created_at: string;
}

export interface InboxItem {
  id: UUID;
  category: "APPROVAL_REQUIRED" | "DECISION_REQUIRED" | "REVIEW_RECOMMENDED" | "COMPLETED" | "FAILED" | "INFO";
  severity: "info" | "low" | "medium" | "high" | "critical";
  objective_id: UUID | null;
  department_id: UUID | null;
  agent_id: UUID | null;
  task_id: UUID | null;
  approval_id: UUID | null;
  artifact_id: UUID | null;
  title: string;
  summary: string;
  is_read: boolean;
  action_required: boolean;
  resolved_at: string | null;
  link: string | null;
  created_at: string;
}

export interface Project {
  id: UUID;
  name: string;
  description: string;
  status: string;
  start_date: string | null;
  target_date: string | null;
  milestones: { title: string; due?: string; done?: boolean }[];
  created_at: string;
  objective_count?: number;
}

export interface Integration {
  id: UUID;
  provider_key: string;
  name: string;
  enabled: boolean;
  status: "connected" | "not_configured" | "error" | "disabled";
  scopes: string[];
  config: Record<string, string>;
  has_secret: boolean;
  secret_last4: string | null;
  health_message: string | null;
  last_checked_at: string | null;
}

export interface OrgSettings {
  default_model: string;
  premium_model: string;
  max_task_iterations: number;
  max_parallel_tasks: number;
  max_review_revisions: number;
  max_messages_per_task: number;
  objective_budget_usd: string;
  daily_budget_usd: string;
  notification_emails: string[];
  timezone: string;
  ceo_name: string | null;
}

export interface AIStatus {
  configured: boolean;
  provider: "organization" | "mock";
  default_model: string | null;
}
