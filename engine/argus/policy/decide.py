"""Class-by-confidence decisions with mandatory human reasons."""

from __future__ import annotations

from argus.config import CONFIG, PolicyConfig
from argus.contracts import (
    Decision,
    DecisionKind,
    HumanGate,
    Verdict,
    VerdictClass,
)


def decide(
    verdict: Verdict,
    *,
    ts: float,
    config: PolicyConfig = CONFIG.policy,
) -> Decision:
    top = max(verdict.classes, key=lambda item: item.p)
    if top.verdict_class is VerdictClass.EXPECTED_SURGE:
        decision = (
            DecisionKind.SUPPRESS
            if verdict.confidence >= config.expected_surge_threshold
            else DecisionKind.ALERT
        )
    elif top.verdict_class is VerdictClass.ATTACK:
        decision = (
            DecisionKind.ACT
            if verdict.confidence >= config.attack_act_threshold
            else DecisionKind.ALERT
        )
    elif top.verdict_class is VerdictClass.CODE_FAULT:
        decision = (
            DecisionKind.ACT
            if verdict.confidence >= config.code_fault_alert_threshold
            else DecisionKind.ALERT
        )
    else:
        decision = (
            DecisionKind.ACT
            if verdict.confidence >= config.operational_act_threshold
            else DecisionKind.ALERT
        )
    evidence = "; ".join(item.note for item in verdict.evidence[:3])
    return Decision(
        decision_id=f"dec-{verdict.incident_id}",
        incident_id=verdict.incident_id,
        ts=ts,
        decision=decision,
        reason=(
            f"{decision} because {top.verdict_class} is the leading cause "
            f"at confidence {verdict.confidence:.2f}: {evidence}"
        ),
        evidence_ref=f"{verdict.incident_id}/verdict",
        confidence=verdict.confidence,
        human_gate=HumanGate(required=False),
    )
