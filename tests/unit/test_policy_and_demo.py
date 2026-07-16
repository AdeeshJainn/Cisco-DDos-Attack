"""Decision, safety, rollback, audit and demonstration snapshot tests."""

from pathlib import Path

import pytest
from argus.audit.log import AuditLog
from argus.contracts import (
    Incident,
    IncidentStatus,
    RollbackTrigger,
    Symptom,
    SymptomKind,
)
from argus.demo import build_demo_snapshot
from argus.policy.decide import decide
from argus.policy.guards import guard_target
from argus.policy.ladder import first_action
from argus.policy.rollback import rollback_for_regression
from argus.verdict.rules import classify


def _attack():
    incident = Incident(
        incident_id="inc-policy",
        status=IncidentStatus.OPEN,
        first_ts=1.0,
        last_ts=40.0,
        symptoms=[
            Symptom(
                service="auth-svc",
                signal="auth_fail_ratio",
                kind=SymptomKind.RATIO_DEFORM,
                onset_ts=1.0,
                score=0.95,
            )
        ],
    )
    verdict = classify(incident)
    decision = decide(verdict, ts=40.0)
    action = first_action(decision, verdict, ts=41.0)
    assert action is not None
    return incident, verdict, decision, action


def test_attack_decision_action_and_reason_are_complete():
    _, _, decision, action = _attack()

    assert decision.reason
    assert decision.evidence_ref
    assert action.blast_radius.protected_cohorts_touched == 0
    assert action.blast_radius.gates_passed


def test_protected_cohorts_are_rejected():
    with pytest.raises(ValueError, match="protected"):
        guard_target(
            "payment-in-flight",
            estimated_pct=1.0,
            max_pct=15.0,
        )


def test_rollback_and_append_only_audit(tmp_path: Path):
    incident, _, decision, action = _attack()
    rollback = rollback_for_regression(
        action,
        ts=100.0,
        cause="protected-user latency regressed",
        checked_signals=["err_rate", "p95_ms"],
        users_restored=True,
        verified_ts=160.0,
    )
    audit = AuditLog(tmp_path / "audit.db")
    audit.append(incident.incident_id, decision.ts, decision)
    audit.append(incident.incident_id, action.ts, action)
    audit.append(incident.incident_id, rollback.ts, rollback)
    rows = audit.export()
    audit.close()

    assert rollback.trigger is RollbackTrigger.AUTO
    assert rollback.verification.users_restored
    assert [row["kind"] for row in rows] == ["decision", "action", "rollback"]


def test_demo_snapshot_contains_attack_action_and_real_code_report():
    snapshot = build_demo_snapshot()

    assert snapshot["mode"] == "seeded deterministic simulation"
    assert snapshot["incidents"][0]["action"]["rung"] == "rate_limit"
    code = snapshot["incidents"][1]["rca"]["code_fault"]
    assert code["commit"]
    assert code["file"] == "payment_svc/retry.py"
    assert code["line"] == 18
    assert "```diff" in snapshot["incidents"][1]["report"]
