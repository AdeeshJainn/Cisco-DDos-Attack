"""Cross-seed invariants over the complete observable-to-action pipeline."""

import pytest
from argus.contracts import CauseClass, DecisionKind
from argus.pipeline import analyze_profile

FRESH_CASES = (
    ("quiet_day", 7101),
    ("match_night", 7102),
    ("cascade_night", 7103),
    ("combo_night", 7104),
)


@pytest.mark.parametrize(("profile", "seed"), FRESH_CASES)
def test_pipeline_invariants_hold_on_fresh_seeds(profile: str, seed: int):
    findings = analyze_profile(profile=profile, seed=seed)

    if profile == "quiet_day":
        assert findings == []
        return

    assert findings
    for finding in findings:
        assert finding.incident.symptoms
        assert finding.verdict.evidence
        assert finding.decision.reason.strip()
        assert finding.decision.evidence_ref.strip()
        assert finding.rca.origin.service
        assert finding.rca.origin.service not in {
            alternate.service for alternate in finding.rca.origin.alternates
        }
        alternate_scores = [alternate.score for alternate in finding.rca.origin.alternates]
        assert alternate_scores == sorted(alternate_scores, reverse=True)
        if finding.action is not None:
            assert finding.decision.decision is DecisionKind.ACT
            assert finding.action.blast_radius.protected_cohorts_touched == 0
            assert finding.action.blast_radius.gates_passed
        if finding.rca.cause_class is CauseClass.CODE_FAULT:
            assert finding.rca.code_fault is not None
            assert finding.rca.code_fault.proposed_fix is not None


def test_combo_causes_remain_separate_and_each_has_one_origin():
    findings = analyze_profile(profile="combo_night", seed=7351)

    assert {finding.rca.cause_class for finding in findings} == {
        CauseClass.ATTACK,
        CauseClass.CODE_FAULT,
        CauseClass.OPERATIONAL_FAULT,
    }
    assert len({finding.incident.incident_id for finding in findings}) == len(findings)
