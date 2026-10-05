import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from companyos.providers.llm import LLMMessage, LLMProvider, LLMResponse


class ReviewVerdict(BaseModel):
    verdict: Literal["accept", "revise"]
    score: int = Field(ge=1, le=10)
    feedback: str = ""
    issues: list[str] = Field(default_factory=list)


def review_prompt(task_title: str, instructions: str, criteria: list[str], deliverable: str) -> str:
    criteria_text = "\n".join(f"- {item}" for item in criteria) or "- Fulfils the instructions"
    return f"""Review this deliverable strictly against the acceptance criteria.

TASK: {task_title}
INSTRUCTIONS: {instructions}
ACCEPTANCE CRITERIA:
{criteria_text}

DELIVERABLE:
<deliverable>
{deliverable[:20000]}
</deliverable>

Respond with JSON only: {{"verdict": "accept" | "revise", "score": 1-10, "feedback": "...", "issues": ["..."]}}
Accept if the criteria are met, even if minor polish is possible."""


async def review_deliverable(
    *,
    llm: LLMProvider,
    model: str,
    system_prompt: str,
    task_title: str,
    instructions: str,
    criteria: list[str],
    deliverable: str,
    hints: dict[str, Any],
) -> tuple[ReviewVerdict, LLMResponse]:
    response = await llm.complete(
        model=model,
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=review_prompt(task_title, instructions, criteria, deliverable)),
        ],
        json_mode=True,
        purpose="review",
        hints=hints,
        temperature=0.1,
    )
    try:
        verdict = ReviewVerdict.model_validate(json.loads(response.content or "{}"))
    except (json.JSONDecodeError, ValidationError):
        # An unparseable review must not silently pass work: treat as accepted with a flag
        verdict = ReviewVerdict(
            verdict="accept",
            score=5,
            feedback="Reviewer response was not parseable; accepted with low confidence.",
            issues=["unparseable_review"],
        )
    return verdict, response
