"""Arbitrary-seed observable-to-decision pipeline acceptance tests."""

import pytest
from argus.contracts import CauseClass, DecisionKind
from argus.pipeline import analyze_profile
from argus.scenario.generate import DEFAULT_SCORED_FROM_TS
from argus.scenario.profiles import build_profile

from scoring.harness import window_iou


@pytest.mark.parametrize("seed", [7001, 8123])
def test_quiet_seed_has_no_false_incident(seed: int):
    assert analyze_profile(profile="quiet_day", seed=seed) == []


def test_fresh_seed_detects_attack_without_labels():
    findings = analyze_profile(profile="match_night", seed=9001)

    assert len(findings) == 1
    assert findings[0].rca.cause_class is CauseClass.ATTACK
    assert findings[0].rca.origin.service == "auth-svc"
    assert findings[0].decision.decision is DecisionKind.ACT
    assert findings[0].decision.reason
    assert findings[0].action is not None


def test_fresh_seed_localizes_real_code_fault_without_labels():
    findings = analyze_profile(profile="cascade_night", seed=9002)
    ground_truth = build_profile(
        "cascade_night",
        DEFAULT_SCORED_FROM_TS,
    ).incidents[0]

    assert len(findings) == 1
    assert findings[0].rca.cause_class is CauseClass.CODE_FAULT
    assert findings[0].rca.origin.service == "payment-svc"
    assert findings[0].rca.code_fault is not None
    assert findings[0].rca.code_fault.file == "payment_svc/retry.py"
    assert findings[0].rca.code_fault.line == 18
    assert findings[0].decision.reason
    assert (
        window_iou(
            (findings[0].incident.first_ts, findings[0].incident.last_ts),
            ground_truth.window,
        )
        >= 0.8
    )


def test_combo_seed_splits_attack_code_and_operations():
    classes = {
        finding.rca.cause_class for finding in analyze_profile(profile="combo_night", seed=9003)
    }

    assert classes == {
        CauseClass.ATTACK,
        CauseClass.CODE_FAULT,
        CauseClass.OPERATIONAL_FAULT,
    }
