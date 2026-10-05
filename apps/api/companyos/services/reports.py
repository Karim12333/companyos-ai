from typing import Any


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(max(seconds, 0), 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m" if hours else f"{minutes}m {remainder % 60}s"


def render_report_markdown(summary: dict[str, Any]) -> str:
    narrative = summary.get("narrative", {})

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) or "- None"

    failures = (
        "\n".join(
            f"- **{item['task']}** ({item.get('category') or 'unknown'}): {item.get('message')}"
            f"{' — recoverable, can be retried' if item.get('recoverable') else ''}"
            for item in summary.get("failures", [])
        )
        or "- None"
    )
    return f"""# Executive Report — {summary.get("objective_title")}

**Status:** {summary.get("status", "").replace("_", " ").title()}
**Duration:** {format_duration(int(summary.get("duration_seconds", 0)))}
**Departments:** {", ".join(summary.get("departments", [])) or "—"}
**Agents involved:** {summary.get("agents_involved", 0)}
**Estimated AI cost:** ${summary.get("cost_usd", 0):.4f}

## Overall assessment
{narrative.get("overall_assessment", "")}

## Delivered
{bullets(summary.get("completed_titles", []))}

## Failures and blocked work
{failures}

## Reviews
{summary.get("revisions_requested", 0)} revision(s) requested and resolved by the review gate.

## Approvals
Total {summary.get("approvals_total", 0)} · approved {summary.get("approvals_approved", 0)} · rejected {summary.get("approvals_rejected", 0)} · pending {summary.get("approvals_pending", 0)}

## Key findings
{bullets(narrative.get("key_findings", []))}

## Risks
{bullets(narrative.get("risks", []))}

## Recommendation
{narrative.get("recommendation", "")}

## Next actions
{bullets(narrative.get("next_actions", []))}
"""
