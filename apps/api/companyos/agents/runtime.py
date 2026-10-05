import uuid
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from companyos.agents.metered import MeteredLLM, MeteringScope
from companyos.observability import logger
from companyos.providers.llm import LLMMessage, LLMProvider, ToolSpec
from companyos.tools import gateway
from companyos.tools.registry import TOOL_REGISTRY, ToolContext


@dataclass
class AgentRunInput:
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    agent_role_key: str
    objective_id: uuid.UUID | None
    task_id: uuid.UUID | None
    task_run_id: uuid.UUID | None
    system_prompt: str
    user_prompt: str
    tool_keys: list[str]
    llm: LLMProvider
    model: str
    embedding_model: str
    temperature: float
    max_iterations: int
    max_messages_per_task: int = 6
    hints: dict[str, Any] = field(default_factory=dict)
    fallback_model: str | None = None


# A tool that keeps failing is withdrawn for the rest of the run instead of burning iterations
MAX_TOOL_FAILURES = 3
FAILED_TOOL_STATUSES = {"error", "invalid", "denied"}


@dataclass
class AgentRunResult:
    final_output: str
    iterations: int
    hit_iteration_limit: bool
    approval_ids: list[str]
    artifact_ids: list[str]
    trace: list[dict[str, Any]]
    escalation_ids: list[str] = field(default_factory=list)


class AgentState(TypedDict):
    messages: list[LLMMessage]
    iterations: int
    final_output: str | None
    hit_limit: bool
    approval_ids: list[str]
    artifact_ids: list[str]
    escalation_ids: list[str]
    trace: list[dict[str, Any]]


def tool_specs(tool_keys: list[str]) -> list[ToolSpec]:
    return [
        ToolSpec(
            name=key, description=TOOL_REGISTRY[key].description, parameters=TOOL_REGISTRY[key].json_schema()
        )
        for key in tool_keys
        if key in TOOL_REGISTRY
    ]


def build_agent_graph(run: AgentRunInput) -> Any:
    specs = tool_specs(run.tool_keys)
    llm = MeteredLLM(
        run.llm,
        MeteringScope(
            organization_id=run.organization_id,
            objective_id=run.objective_id,
            task_id=run.task_id,
            task_run_id=run.task_run_id,
            agent_id=run.agent_id,
            fallback_model=run.fallback_model,
        ),
    )
    tool_failures: dict[str, int] = {}
    context = ToolContext(
        organization_id=run.organization_id,
        agent_id=run.agent_id,
        agent_role_key=run.agent_role_key,
        objective_id=run.objective_id,
        task_id=run.task_id,
        task_run_id=run.task_run_id,
        llm=run.llm,
        embedding_model=run.embedding_model,
        max_messages_per_task=run.max_messages_per_task,
    )

    async def think(state: AgentState) -> dict[str, Any]:
        available = [spec for spec in specs if tool_failures.get(spec.name, 0) < MAX_TOOL_FAILURES]
        response = await llm.complete(
            model=run.model,
            messages=state["messages"],
            tools=available,
            temperature=run.temperature,
            purpose="execute",
            hints=run.hints,
        )
        message = LLMMessage(role="assistant", content=response.content, tool_calls=response.tool_calls)
        trace_entry = {
            "step": "think",
            "iteration": state["iterations"] + 1,
            "tool_calls": [call.name for call in response.tool_calls],
            "tokens": response.input_tokens + response.output_tokens,
        }
        update: dict[str, Any] = {
            "messages": [*state["messages"], message],
            "iterations": state["iterations"] + 1,
            "trace": [*state["trace"], trace_entry],
        }
        if not response.tool_calls:
            update["final_output"] = response.content or ""
        return update

    async def act(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        messages = list(state["messages"])
        trace = list(state["trace"])
        approvals = list(state["approval_ids"])
        artifacts = list(state["artifact_ids"])
        escalations = list(state["escalation_ids"])
        withdrawn: list[str] = []
        for call in last.tool_calls:
            outcome = await gateway.invoke(context, call.name, call.arguments)
            messages.append(
                LLMMessage(role="tool", content=outcome.content, tool_call_id=call.id, name=call.name)
            )
            trace.append({"step": "tool", "tool": call.name, "status": outcome.status})
            if outcome.status in FAILED_TOOL_STATUSES:
                tool_failures[call.name] = tool_failures.get(call.name, 0) + 1
                if tool_failures[call.name] == MAX_TOOL_FAILURES:
                    logger.warning("tool_withdrawn", tool=call.name, task_id=str(run.task_id))
                    trace.append({"step": "tool_withdrawn", "tool": call.name})
                    withdrawn.append(call.name)
            if outcome.approval_id:
                approvals.append(str(outcome.approval_id))
            if "artifact_id" in outcome.data:
                artifacts.append(str(outcome.data["artifact_id"]))
            if "escalation_id" in outcome.data:
                escalations.append(str(outcome.data["escalation_id"]))
        for name in withdrawn:
            # Appended after all tool results so the conversation stays valid for the provider
            messages.append(
                LLMMessage(
                    role="user",
                    content=f"The tool '{name}' failed {MAX_TOOL_FAILURES} times and is no longer available. "
                    "Finish the task without it and state the limitation in your output.",
                )
            )
        update: dict[str, Any] = {
            "messages": messages,
            "trace": trace,
            "approval_ids": approvals,
            "artifact_ids": artifacts,
            "escalation_ids": escalations,
        }
        if escalations:
            # The task now waits for the CEO; the agent must not keep working on it
            update["final_output"] = "Escalated to the CEO; waiting for a decision."
        return update

    async def force_finish(state: AgentState) -> dict[str, Any]:
        # Hard stop: no endless loops regardless of what the model wants
        return {
            "hit_limit": True,
            "final_output": "Stopped at the iteration limit before the agent declared completion.",
        }

    def after_think(state: AgentState) -> str:
        if state.get("final_output") is not None:
            return END
        return "act"

    def after_act(state: AgentState) -> str:
        if state["escalation_ids"]:
            return END
        return "force_finish" if state["iterations"] >= run.max_iterations else "think"

    graph = StateGraph(AgentState)
    graph.add_node("think", think)
    graph.add_node("act", act)
    graph.add_node("force_finish", force_finish)
    graph.add_edge(START, "think")
    graph.add_conditional_edges("think", after_think, {"act": "act", END: END})
    graph.add_conditional_edges(
        "act", after_act, {"think": "think", "force_finish": "force_finish", END: END}
    )
    graph.add_edge("force_finish", END)
    return graph.compile()


async def run_agent(run: AgentRunInput) -> AgentRunResult:
    graph = build_agent_graph(run)
    initial: AgentState = {
        "messages": [
            LLMMessage(role="system", content=run.system_prompt),
            LLMMessage(role="user", content=run.user_prompt),
        ],
        "iterations": 0,
        "final_output": None,
        "hit_limit": False,
        "approval_ids": [],
        "artifact_ids": [],
        "escalation_ids": [],
        "trace": [],
    }
    state = await graph.ainvoke(initial, config={"recursion_limit": run.max_iterations * 3 + 5})
    return AgentRunResult(
        final_output=state.get("final_output") or "",
        iterations=state["iterations"],
        hit_iteration_limit=state.get("hit_limit", False),
        approval_ids=state["approval_ids"],
        artifact_ids=state["artifact_ids"],
        trace=state["trace"],
        escalation_ids=state["escalation_ids"],
    )
