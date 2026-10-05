import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from companyos.providers.llm import LLMMessage, LLMProvider, LLMResponse


class ReportNarrative(BaseModel):
    headline: str
    overall_assessment: str
    key_findings: list[str] = Field(default_factory=list)
    recommendation: str
    next_actions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


def report_prompt(stats: dict[str, Any], deliverables: str) -> str:
    return f"""Write the executive report for this objective. Be honest about failures and pending approvals.

FACTS (authoritative, computed by the platform):
{json.dumps(stats, indent=2, default=str)}

DELIVERABLE EXCERPTS:
{deliverables[:15000]}

Respond with JSON only:
{{"headline": "...", "overall_assessment": "...", "key_findings": ["..."], "recommendation": "...",
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
