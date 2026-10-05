from decimal import Decimal

from companyos.models.enums import PermissionEffect, RiskLevel
from companyos.tools.policy import Decision, PolicyInput, evaluate


def make_input(**overrides: object) -> PolicyInput:
    values: dict[str, object] = {
        "tool_key": "create_artifact",
        "tool_registered": True,
        "risk_level": RiskLevel.AUTONOMOUS,
        "agent_active": True,
        "agent_tool_keys": frozenset({"create_artifact", "publish_social_post", "schedule_social_post"}),
    }
    values.update(overrides)
    return PolicyInput(**values)  # type: ignore[arg-type]


def test_level_one_tool_is_allowed() -> None:
    assert evaluate(make_input()).decision == Decision.ALLOW


def test_unknown_tool_is_denied() -> None:
    assert evaluate(make_input(tool_key="rm_rf", tool_registered=False)).decision == Decision.DENY


def test_tool_not_granted_to_agent_is_denied() -> None:
    result = evaluate(make_input(tool_key="web_search"))
    assert result.decision == Decision.DENY
    assert "not authorized" in result.reason


def test_inactive_agent_is_denied() -> None:
    assert evaluate(make_input(agent_active=False)).decision == Decision.DENY


def test_level_three_always_requires_approval_even_if_explicitly_allowed() -> None:
    result = evaluate(
        make_input(
            tool_key="publish_social_post",
            risk_level=RiskLevel.HUMAN_APPROVAL,
            agent_permissions={"publish_social_post": PermissionEffect.ALLOW},
        )
    )
    assert result.decision == Decision.REQUIRE_APPROVAL


def test_objective_can_forbid_external_actions() -> None:
    result = evaluate(
        make_input(
            tool_key="publish_social_post",
            risk_level=RiskLevel.HUMAN_APPROVAL,
            objective_external_actions="deny",
        )
    )
    assert result.decision == Decision.DENY


def test_level_two_follows_organization_policy() -> None:
    base = {"tool_key": "schedule_social_post", "risk_level": RiskLevel.CONTROLLED}
    assert evaluate(make_input(**base)).decision == Decision.REQUIRE_APPROVAL
    relaxed = make_input(**base, org_requires_approval={"schedule_social_post": False})
    assert evaluate(relaxed).decision == Decision.ALLOW


def test_explicit_deny_beats_everything() -> None:
    result = evaluate(make_input(agent_permissions={"create_artifact": PermissionEffect.DENY}))
    assert result.decision == Decision.DENY


def test_budget_exhaustion_denies() -> None:
    objective = make_input(objective_cost_usd=Decimal("5"), objective_budget_usd=Decimal("5"))
    daily = make_input(daily_cost_usd=Decimal("21"), daily_budget_usd=Decimal("20"))
    assert evaluate(objective).decision == Decision.DENY
    assert evaluate(daily).decision == Decision.DENY
