# Agent System

Agents are **configuration, not code**. Adding a role means inserting rows, not writing logic.

## Agent definition

| Property | Where |
|---|---|
| name, role key, title, description | `agents` |
| system instructions, goals, responsibilities | `agents` |
| department, reporting manager | `agents.department_id`, `agents.manager_agent_id` |
| agents it can delegate to | `agent_relationships` (kind `can_delegate_to`) |
| tools | `agent_tools` |
| explicit permissions (allow / require approval / deny) | `agent_permissions` |
| model, premium flag, temperature, max iterations | `agents` |
| memory configuration, active flag, status | `agents` |

Templates (`companyos/templates`) instantiate these rows. V1 ships **Software / AI Company**:
Executive Office (Chief of Staff, Reviewer, Executive Reporter), Research (Market Researcher),
Product (Product Manager), Engineering (Technical Architect, Software Engineer),
Marketing (Marketing Strategist, Copywriter).

## Roles in the execution loop

| Role | Responsibility |
|---|---|
| Chief of Staff (coordinator) | Turns the objective into a validated task DAG (LangGraph: draft, validate, repair) |
| Specialists | Execute tasks with tools and save deliverables as artifacts |
| Reviewer | Judges each deliverable against acceptance criteria and requests bounded revisions |
| Executive Reporter | Writes the final report narrative from platform-computed facts |

## Agent runtime (`companyos/agents/runtime.py`)

LangGraph state machine: think, act, think ... END, with `force_finish` at the iteration limit.

- **think:** budget check, one LLM call with only the agent's allowed tools, usage recorded.
- **act:** each tool call goes through the **tool gateway** (`companyos/tools/gateway.py`).
- Limits: `min(agent.max_iterations, org.max_task_iterations)`, messages per task, delegations per task (3)
  and delegation depth (2). Endless loops are impossible by construction.

## Prompts

System prompt = agent instructions + goals + active CEO preferences + non-negotiable platform rules
(`agents/prompts.py`). The task prompt carries the objective, instructions, acceptance criteria,
summaries and artifact ids of dependency outputs, and reviewer feedback on revisions.

## Communication

`agent_messages` are always tied to objective, task, sender, recipient, kind and reason:

- `delegation`: Chief of Staff assignments and manager delegations
- `handoff`: completed work delivered to the agents of dependent tasks
- `feedback`: reviewer revision requests and approvals
- `request`: agent-initiated messages via `send_message` (bounded per task)

## Tools (`companyos/tools/registry.py`)

| Tool | Risk | Notes |
|---|---|---|
| `search_company_knowledge` | 1 | facts, preferences and pgvector chunks (untrusted content wrapped) |
| `create_artifact` | 1 | versioned artifact in object storage |
| `read_artifact` | 1 | list or read artifacts of the objective |
| `send_message` | 1 | bounded agent-to-agent message |
| `delegate_task` | 1 | only to `can_delegate_to` agents; creates a child task |
| `web_search` | 1 | Tavily with the organization key; results are untrusted |
| `schedule_social_post` | 2 | organization approval policy decides |
| `publish_social_post` | 3 | always CEO approval (sandbox integration) |
| `send_external_email` | 3 | always CEO approval (sandbox; never delivered externally in V1) |

## Model resolution

Organization AI provider, then (development only) the platform fallback key, then the offline mock model.
See ADR-0006 and ADR-0007.
