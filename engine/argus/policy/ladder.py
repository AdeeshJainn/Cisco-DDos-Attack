"""First reversible rung of the graduated action ladder."""

from __future__ import annotations

from argus.config import CONFIG, PolicyConfig
from argus.contracts import (
    Action,
    ActionRung,
    ActionTarget,
    BlastRadius,
    Decision,
    DecisionKind,
    TargetKind,
    Verdict,
    VerdictClass,
)

from .guards import guard_target


def first_action(
    decision: Decision,
    verdict: Verdict,
    *,
    ts: float,
    config: PolicyConfig = CONFIG.policy,
) -> Action | None:
    if decision.decision is not DecisionKind.ACT:
        return None
    top = max(verdict.classes, key=lambda item: item.p).verdict_class
    if top is VerdictClass.ATTACK:
        rung = ActionRung.RATE_LIMIT
        target_kind = TargetKind.COHORT
        selector = "behaviorally-anomalous-clients"
        max_pct = config.rate_limit_max_pct
        expected = "reduce unexplained traffic while preserving event users"
    elif top is VerdictClass.CODE_FAULT:
        rung = ActionRung.THROTTLE
        target_kind = TargetKind.SERVICE
        selector = verdict.evidence[0].feature.split(".", maxsplit=1)[0]
        max_pct = config.throttle_max_pct
        expected = "cap deploy-correlated amplification while the code repair is reviewed"
    else:
        rung = ActionRung.SCALE_OUT
        target_kind = TargetKind.SERVICE
        selector = verdict.evidence[0].feature.split(".", maxsplit=1)[0]
        max_pct = 0.0
        expected = "restore capacity headroom and reduce queueing pressure"
    estimated_pct = max_pct
    gates = guard_target(
        selector,
        estimated_pct=estimated_pct,
        max_pct=max_pct,
        config=config,
    )
    gates.insert(0, f"confidence>={decision.confidence:.2f}")
    return Action(
        action_id=f"act-{decision.incident_id}-01",
        decision_id=decision.decision_id,
        ts=ts,
        rung=rung,
        target=ActionTarget(
            kind=target_kind,
            selector=selector,
            est_traffic_pct=estimated_pct,
        ),
        blast_radius=BlastRadius(
            protected_cohorts_touched=0,
            max_pct_allowed=max_pct,
            gates_passed=gates,
        ),
        trigger=decision.reason,
        expected_effect=expected,
    )
