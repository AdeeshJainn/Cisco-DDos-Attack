"""P4.4 rule verdicts, combination handling and evidence reasons."""

import pytest
from argus.contracts import (
    Incident,
    IncidentStatus,
    Symptom,
    SymptomKind,
    VerdictClass,
)
from argus.verdict.rules import classify


def _incident(*kinds: SymptomKind) -> Incident:
    return Incident(
        incident_id="inc-test",
        status=IncidentStatus.OPEN,
        first_ts=10.0,
        last_ts=40.0,
        symptoms=[
            Symptom(
                service="edge-gw" if kind is not SymptomKind.DEPLOY_MARKER else "payment-svc",
                signal=kind,
                kind=kind,
                onset_ts=10.0 + index,
                score=0.8 + 0.02 * index,
            )
            for index, kind in enumerate(kinds)
        ],
    )


def _top(verdict):
    return max(verdict.classes, key=lambda item: item.p).verdict_class


@pytest.mark.parametrize(
    ("incident", "event_explained", "expected"),
    [
        (_incident(SymptomKind.RESIDUAL_EXCEED), True, VerdictClass.EXPECTED_SURGE),
        (
            _incident(SymptomKind.RESIDUAL_EXCEED, SymptomKind.RATIO_DEFORM),
            False,
            VerdictClass.ATTACK,
        ),
        (
            _incident(
                SymptomKind.DEPLOY_MARKER,
                SymptomKind.LOG_BURST,
                SymptomKind.EDGE_DEGRADED,
            ),
            False,
            VerdictClass.CODE_FAULT,
        ),
        (
            _incident(SymptomKind.SATURATION, SymptomKind.EDGE_DEGRADED),
            False,
            VerdictClass.OPERATIONAL_FAULT,
        ),
    ],
)
def test_ordered_rules_choose_expected_class(incident, event_explained, expected):
    verdict = classify(incident, event_explained=event_explained)

    assert _top(verdict) is expected
    assert verdict.evidence
    assert all(item.note.strip() for item in verdict.evidence)
    assert abs(sum(item.p for item in verdict.classes) - 1.0) < 1e-9


def test_attack_plus_deploy_marks_combination_and_splits_probability():
    verdict = classify(
        _incident(
            SymptomKind.RATIO_DEFORM,
            SymptomKind.DEPLOY_MARKER,
            SymptomKind.LOG_BURST,
        )
    )
    probabilities = {item.verdict_class: item.p for item in verdict.classes}

    assert verdict.combination
    assert probabilities[VerdictClass.ATTACK] == probabilities[VerdictClass.CODE_FAULT]
    assert probabilities[VerdictClass.ATTACK] > probabilities[VerdictClass.EXPECTED_SURGE]


def test_more_corroboration_raises_but_caps_confidence():
    single = classify(_incident(SymptomKind.RATIO_DEFORM))
    multiple = classify(
        _incident(
            SymptomKind.RATIO_DEFORM,
            SymptomKind.RESIDUAL_EXCEED,
            SymptomKind.EDGE_DEGRADED,
        )
    )

    assert multiple.confidence > single.confidence
    assert multiple.confidence <= 0.95
