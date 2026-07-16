"""Per-incident RCA report generation in markdown and JSON."""

from __future__ import annotations

from argus.contracts import Incident, RcaResult, Verdict


def report_markdown(
    incident: Incident,
    verdict: Verdict,
    rca: RcaResult,
) -> str:
    top = max(verdict.classes, key=lambda item: item.p)
    lines = [
        f"# Incident {incident.incident_id}",
        "",
        f"- Window: `{incident.first_ts:.0f}` → `{incident.last_ts:.0f}`",
        f"- Verdict: **{top.verdict_class}** ({verdict.confidence:.0%})",
        f"- Origin: **{rca.origin.service}**",
        f"- Cure: **{rca.cure.kind}** — {rca.cure.justification}",
        "",
        "## Evidence chain",
        "",
        *[f"- {line}" for line in rca.collapse_trace],
    ]
    if rca.code_fault is not None:
        finding = rca.code_fault
        lines.extend(
            [
                "",
                "## Code finding",
                "",
                f"- Commit: `{finding.commit}`",
                f"- Location: `{finding.file}:{finding.line}` (`{finding.function}`)",
                f"- Mechanism: {finding.mechanism}",
            ]
        )
        if finding.proposed_fix is not None:
            lines.extend(
                [
                    f"- Proposed fix: {finding.proposed_fix.summary}",
                    "",
                    "```diff",
                    finding.proposed_fix.diff,
                    "```",
                ]
            )
    return "\n".join(lines) + "\n"
