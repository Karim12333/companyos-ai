import json
import uuid
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError

from companyos.db import tenant_scope
from companyos.models.enums import Priority
from companyos.providers.llm import LLMMessage, LLMProvider
from companyos.services.usage import record_usage

MAX_PLAN_TASKS = 15
MAX_PLAN_ATTEMPTS = 3
NON_PLANNABLE_ROLES = {"reviewer", "executive_reporter"}


class PlannedTask(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{2,60}$")
    title: str = Field(min_length=3, max_length=200)
    role: str
    instructions: str = Field(min_length=10, max_length=4000)
    depends_on: list[str] = Field(default_factory=list)
    expected_output_type: str = "document"
    acceptance_criteria: list[str] = Field(default_factory=list)
    requires_review: bool = True
    priority: Priority = Priority.NORMAL


class Plan(BaseModel):
    summary: str = Field(max_length=2000)
    tasks: list[PlannedTask] = Field(min_length=1, max_length=MAX_PLAN_TASKS)


class PlanningError(Exception):
    pass


@dataclass
class RoleOption:
    role_key: str
    title: str
    department: str
    responsibilities: list[str]


def validate_plan(plan: Plan, available_roles: set[str]) -> list[str]:
    """Checks the plan is a valid, executable DAG for this organization."""
    errors: list[str] = []
    keys = [task.key for task in plan.tasks]
    if len(keys) != len(set(keys)):
        errors.append("Task keys must be unique")
    key_set = set(keys)
    for task in plan.tasks:
        if task.role not in available_roles:
            errors.append(f"Task '{task.key}' uses unknown role '{task.role}'")
        if task.role in NON_PLANNABLE_ROLES:
            errors.append(f"Task '{task.key}': role '{task.role}' is applied automatically, do not plan it")
        for dependency in task.depends_on:
            if dependency == task.key:
                errors.append(f"Task '{task.key}' depends on itself")
            elif dependency not in key_set:
                errors.append(f"Task '{task.key}' depends on unknown task '{dependency}'")
    if not errors and has_cycle({task.key: task.depends_on for task in plan.tasks}):
        errors.append("Dependencies contain a cycle")
    return errors


def has_cycle(graph: dict[str, list[str]]) -> bool:
    # Kahn's algorithm: a cycle exists if not every node can be ordered
    remaining = {node: set(dependencies) for node, dependencies in graph.items()}
    ready = [node for node, dependencies in remaining.items() if not dependencies]
    ordered = 0
    while ready:
        node = ready.pop()
        ordered += 1
        for other, dependencies in remaining.items():
            if node in dependencies:
                dependencies.remove(node)
                if not dependencies:
                    ready.append(other)
    return ordered != len(graph)


def planning_prompt(objective_title: str, instruction: str, context: str, roles: list[RoleOption]) -> str:
    role_lines = "\n".join(
        f"- {role.role_key} ({role.title}, {role.department}): {', '.join(role.responsibilities)}"
        for role in roles
        if role.role_key not in NON_PLANNABLE_ROLES
    )
    return f"""Create an execution plan for this CEO objective.

OBJECTIVE: {objective_title}
INSTRUCTION: {instruction}
CONTEXT: {context or "(none)"}

AVAILABLE ROLES (use only these role keys):
{role_lines}

Rules:
- 3 to {MAX_PLAN_TASKS} tasks. Each task produces one concrete deliverable.
- Use depends_on to express what must finish first; independent tasks run in parallel.
- Do not plan review or the final executive report — the platform does both automatically.
- External actions (publishing, emailing) are allowed only as requests; the platform gates them.

Respond with JSON only:
{{"summary": "...", "tasks": [{{"key": "snake_case_id", "title": "...", "role": "role_key",
"instructions": "...", "depends_on": ["other_key"], "expected_output_type": "document",
"acceptance_criteria": ["..."], "requires_review": true, "priority": "normal"}}]}}"""


class PlanState(TypedDict):
    messages: list[LLMMessage]
    attempts: int
    plan: Plan | None
    errors: list[str]


async def create_plan(
    *,
    organization_id: uuid.UUID,
    objective_id: uuid.UUID,
    coordinator_agent_id: uuid.UUID | None,
    system_prompt: str,
    objective_title: str,
    instruction: str,
    context: str,
    roles: list[RoleOption],
    llm: LLMProvider,
    model: str,
) -> Plan:
    available = {role.role_key for role in roles}
    hints: dict[str, Any] = {
        "objective_title": objective_title,
        "instruction": instruction,
        "roles": [{"role_key": role.role_key} for role in roles],
    }

    async def draft(state: PlanState) -> dict[str, Any]:
        response = await llm.complete(
            model=model,
            messages=state["messages"],
            json_mode=True,
            purpose="plan",
            hints=hints,
            temperature=0.2,
        )
        async with tenant_scope(organization_id) as session:
            await record_usage(
                session,
                organization_id=organization_id,
                response=response,
                purpose="plan",
                objective_id=objective_id,
                agent_id=coordinator_agent_id,
            )
        messages = [*state["messages"], LLMMessage(role="assistant", content=response.content)]
        try:
            plan = Plan.model_validate(json.loads(response.content or "{}"))
        except (json.JSONDecodeError, ValidationError) as error:
            return {
                "messages": messages,
                "attempts": state["attempts"] + 1,
                "plan": None,
                "errors": [str(error)[:1500]],
            }
        return {
            "messages": messages,
            "attempts": state["attempts"] + 1,
            "plan": plan,
            "errors": validate_plan(plan, available),
        }

    async def repair(state: PlanState) -> dict[str, Any]:
        feedback = "The plan is invalid. Fix these problems and return the full JSON plan:\n- " + "\n- ".join(
            state["errors"]
        )
        return {"messages": [*state["messages"], LLMMessage(role="user", content=feedback)]}

    def route(state: PlanState) -> str:
        if not state["errors"]:
            return END
        return "repair" if state["attempts"] < MAX_PLAN_ATTEMPTS else END

    graph = StateGraph(PlanState)
    graph.add_node("draft", draft)
    graph.add_node("repair", repair)
    graph.add_edge(START, "draft")
    graph.add_conditional_edges("draft", route, {"repair": "repair", END: END})
    graph.add_edge("repair", "draft")
    compiled = graph.compile()
    result = await compiled.ainvoke(
        {
            "messages": [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(
                    role="user", content=planning_prompt(objective_title, instruction, context, roles)
                ),
            ],
            "attempts": 0,
            "plan": None,
            "errors": [],
        }
    )
    if result["errors"] or result["plan"] is None:
        raise PlanningError("Could not produce a valid plan: " + "; ".join(result["errors"])[:1500])
    return result["plan"]
