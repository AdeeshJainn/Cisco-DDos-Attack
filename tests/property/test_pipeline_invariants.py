"""Cross-seed invariants over the complete observable-to-action pipeline."""

import importlib.util
import os
from pathlib import Path

import pytest
from argus.config import CONFIG
from argus.contracts import ActionRung, CauseClass, DecisionKind
from argus.pipeline import analyze_profile

REPO = Path(__file__).resolve().parents[2]
_lint_spec = importlib.util.spec_from_file_location(
    "lint_labels_isolation",
    REPO / "scripts" / "lint_labels_isolation.py",
)
assert _lint_spec is not None and _lint_spec.loader is not None
_labels_lint = importlib.util.module_from_spec(_lint_spec)
_lint_spec.loader.exec_module(_labels_lint)

# GitHub Actions supplies a different run id on every execution. Local runs
# retain a stable seed so failures remain directly reproducible.
BASE_SEED = int(os.getenv("ARGUS_PROPERTY_SEED", "7100")) % 1_000_000
FRESH_CASES = (
    ("quiet_day", BASE_SEED + 1),
    ("match_night", BASE_SEED + 2),
    ("cascade_night", BASE_SEED + 3),
    ("combo_night", BASE_SEED + 4),
)


@pytest.mark.parametrize(("profile", "seed"), FRESH_CASES)
def test_i1_to_i5_and_i8_hold_on_fresh_seeds(profile: str, seed: int):
    findings = analyze_profile(profile=profile, seed=seed)

    # I1: a quiet profile never causes an autonomous action.
    if profile == "quiet_day":
        assert findings == []
        return

    assert findings
    for finding in findings:
        # I2: incidents carry symptoms; actions require an open incident.
        assert finding.incident.symptoms
        assert finding.verdict.evidence
        if finding.action is not None:
            assert finding.incident.status.value == "open"
            assert finding.decision.decision is DecisionKind.ACT

        # I5: every shipped decision carries a reason and evidence reference.
        assert finding.decision.reason.strip()
        assert finding.decision.evidence_ref.strip()

        # I8: RCA always selects exactly one origin and ranks distinct alternates.
        assert finding.rca.origin.service
        assert finding.rca.origin.service not in {
            alternate.service for alternate in finding.rca.origin.alternates
        }
        alternate_scores = [alternate.score for alternate in finding.rca.origin.alternates]
        assert alternate_scores == sorted(alternate_scores, reverse=True)

        if finding.action is not None:
            # I3: the first autonomous action can never cold-start at isolate.
            assert finding.action.rung is not ActionRung.ISOLATE

            # I4: protected cohorts cannot appear in an action selector.
            selector = finding.action.target.selector.casefold()
            assert all(
                cohort.casefold() not in selector for cohort in CONFIG.policy.protected_cohorts
            )
            assert finding.action.blast_radius.protected_cohorts_touched == 0
            assert finding.action.blast_radius.gates_passed

        if finding.rca.cause_class is CauseClass.CODE_FAULT:
            assert finding.rca.code_fault is not None
            assert finding.rca.code_fault.proposed_fix is not None


@pytest.mark.parametrize(("profile", "seed"), FRESH_CASES)
def test_i6_decision_transcript_is_deterministic(profile: str, seed: int):
    first = [finding.model_dump() for finding in analyze_profile(profile=profile, seed=seed)]
    second = [finding.model_dump() for finding in analyze_profile(profile=profile, seed=seed)]

    assert first == second


def test_i7_runtime_is_isolated_from_ground_truth_labels():
    assert _labels_lint.find_violations() == []


def test_i8_combo_causes_remain_separate_and_each_has_one_origin():
    findings = analyze_profile(profile="combo_night", seed=BASE_SEED + 51)

    assert {finding.rca.cause_class for finding in findings} == {
        CauseClass.ATTACK,
        CauseClass.CODE_FAULT,
        CauseClass.OPERATIONAL_FAULT,
    }
    assert len({finding.incident.incident_id for finding in findings}) == len(findings)
