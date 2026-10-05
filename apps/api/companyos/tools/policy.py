from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from companyos.models.enums import PermissionEffect, RiskLevel


class Decision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyInput:
    tool_key: str
    tool_registered: bool
    risk_level: RiskLevel
    agent_active: bool
    agent_tool_keys: frozenset[str]
    agent_permissions: dict[str, PermissionEffect] = field(default_factory=dict)
    org_requires_approval: dict[str, bool] = field(default_factory=dict)
    objective_external_actions: str = "require_approval"
    objective_cost_usd: Decimal = Decimal("0")
    objective_budget_usd: Decimal | None = None
    daily_cost_usd: Decimal = Decimal("0")
    daily_budget_usd: Decimal | None = None


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    reason: str
    risk_level: RiskLevel


def evaluate(policy_input: PolicyInput) -> PolicyDecision:
    """Decides whether an agent may run a tool. Pure function: no I/O, fully unit-testable."""
    risk = policy_input.risk_level

    def result(decision: Decision, reason: str) -> PolicyDecision:
        return PolicyDecision(decision=decision, reason=reason, risk_level=risk)

    if not policy_input.tool_registered:
        return result(Decision.DENY, f"Unknown tool '{policy_input.tool_key}'")
    if not policy_input.agent_active:
        return result(Decision.DENY, "Agent is inactive")
    if policy_input.tool_key not in policy_input.agent_tool_keys:
        return result(Decision.DENY, f"Agent is not authorized to use '{policy_input.tool_key}'")
    explicit = policy_input.agent_permissions.get(policy_input.tool_key)
    if explicit == PermissionEffect.DENY:
        return result(Decision.DENY, "Denied by agent permission")
    if risk == RiskLevel.HUMAN_APPROVAL and policy_input.objective_external_actions == "deny":
        return result(Decision.DENY, "Objective policy forbids external actions")
    budget = policy_input.objective_budget_usd
    if budget is not None and policy_input.objective_cost_usd >= budget:
        return result(Decision.DENY, f"Objective budget of ${budget} exhausted")
    daily = policy_input.daily_budget_usd
    if daily is not None and policy_input.daily_cost_usd >= daily:
        return result(Decision.DENY, f"Daily AI budget of ${daily} exhausted")
    if risk == RiskLevel.HUMAN_APPROVAL:
        return result(Decision.REQUIRE_APPROVAL, "Level 3 action always requires CEO approval")
    if explicit == PermissionEffect.REQUIRE_APPROVAL:
        return result(Decision.REQUIRE_APPROVAL, "Agent permission requires approval")
    if risk == RiskLevel.CONTROLLED and policy_input.org_requires_approval.get(policy_input.tool_key, True):
        return result(Decision.REQUIRE_APPROVAL, "Organization policy requires approval for this action")
    return result(Decision.ALLOW, "Allowed")
