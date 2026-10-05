import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from companyos.providers.llm import LLMMessage, LLMProvider, LLMResponse

CRITERION_STATUSES = ("PASS", "PARTIAL", "FAIL", "UNKNOWN")
GOAL_STATUSES = ("ACHIEVED", "PARTIALLY_ACHIEVED", "NOT_ACHIEVED", "UNKNOWN")


class CriterionAssessment(BaseModel):
    criterion: str
    status: str = "UNKNOWN"
    evidence: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class GoalAssessment(BaseModel):
    status: str = "UNKNOWN"
    summary: str = ""


class ReportNarrative(BaseModel):
    headline: str
    overall_assessment: str
    key_findings: list[str] = Field(default_factory=list)
    recommendation: str
    next_actions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    criteria_assessment: list[CriterionAssessment] = Field(default_factory=list)
    goal_assessment: GoalAssessment = Field(default_factory=GoalAssessment)
    recommendation_evidence: list[str] = Field(default_factory=list)


def report_prompt(stats: dict[str, Any], deliverables: str) -> str:
    return f"""Write the executive report for this objective. Be honest about failures and pending approvals.

FACTS (authoritative, computed by the platform):
{json.dumps(stats, indent=2, default=str)}

DELIVERABLE EXCERPTS:
{deliverables[:15000]}

Assess EVERY objective acceptance criterion in FACTS as PASS, PARTIAL, FAIL or UNKNOWN, citing evidence refs
(E-xxxxxx) from FACTS.evidence when they support it. Do not claim PASS without support. Then give an overall
goal_assessment: ACHIEVED, PARTIALLY_ACHIEVED, NOT_ACHIEVED or UNKNOWN.

Respond with JSON only:
{{"headline": "...", "criteria_assessment": [{{"criterion": "...", "status": "PASS",
"evidence": "...", "evidence_refs": ["E-..."]}}], "goal_assessment": {{"status": "...", "summary": "..."}},
"recommendation_evidence": ["E-..."], "overall_assessment": "...", "key_findings": ["..."], "recommendation": "...",
"next_actions": ["..."], "risks": ["..."]}}"""


async def write_report(
    *, llm: LLMProvider, model: str, system_prompt: str, stats: dict[str, Any], deliverables: str
) -> tuple[ReportNarrative, LLMResponse]:
    response = await llm.complete(
        model=model,
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=report_prompt(stats, deliverables)),
        ],
        json_mode=True,
        purpose="report",
        hints={"stats": stats},
        temperature=0.2,
    )
    try:
        narrative = ReportNarrative.model_validate(json.loads(response.content or "{}"))
    except (json.JSONDecodeError, ValidationError):
        narrative = ReportNarrative(
            headline=f"{stats.get('objective_title')} — {stats.get('status')}",
            overall_assessment="The reporter's narrative could not be parsed; facts below are authoritative.",
            recommendation="Review the deliverables directly.",
        )
    return narrative, response


def normalize_assessment(
    narrative: dict[str, Any], criteria: list[str], evidence_refs: set[str]
) -> dict[str, Any]:
    """Every objective criterion gets exactly one assessment; unknown statuses/refs are never trusted."""
    given = {
        item.get("criterion", "").strip().lower(): item for item in narrative.get("criteria_assessment", [])
    }
    by_index = narrative.get("criteria_assessment", [])
    known = {criterion.strip().lower() for criterion in criteria}
    assessments = []
    for index, criterion in enumerate(criteria):
        positional = by_index[index] if index < len(by_index) else {}
        # Position is only trusted when that entry does not name a different real criterion
        if str(positional.get("criterion", "")).strip().lower() in known:
            positional = {}
        item = given.get(criterion.strip().lower()) or positional
        status = str(item.get("status", "UNKNOWN")).upper()
        assessments.append(
            {
                "criterion": criterion,
                "status": status if status in CRITERION_STATUSES else "UNKNOWN",
                "evidence": str(item.get("evidence", "")) or "Not assessed by the reporter.",
                "evidence_refs": [ref for ref in item.get("evidence_refs", []) if ref in evidence_refs],
            }
        )
    goal = narrative.get("goal_assessment") or {}
    goal_status = str(goal.get("status", "UNKNOWN")).upper()
    return {
        **narrative,
        "criteria_assessment": assessments,
        "goal_assessment": {
            "status": goal_status if goal_status in GOAL_STATUSES else "UNKNOWN",
            "summary": str(goal.get("summary", "")),
        },
        "recommendation_evidence": [
            ref for ref in narrative.get("recommendation_evidence", []) if ref in evidence_refs
        ],
    }
