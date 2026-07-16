"""P4.3 six symptom kinds and hysteresis."""

import pytest
from argus.contracts import (
    DecompFrame,
    DeployRecord,
    MetricName,
    SymptomKind,
    TraceRecord,
)
from argus.detection.ratios import RatioObservation
from argus.detection.symptoms import SymptomDetector


def test_residual_gate_opens_after_sustain_and_closes_below_release():
    detector = SymptomDetector()
    transitions = []
    for ts in range(32):
        transition = detector.residual(
            DecompFrame(
                ts=ts,
                service="edge-gw",
                signal=MetricName.RPS,
                observed=200.0,
                explained_base=100.0,
                explained_event=0.0,
                residual=100.0,
                band=(90.0, 110.0),
                residual_score=0.9,
            )
        )
        if transition:
            transitions.append(transition)
    closed = detector.update(
        service="edge-gw",
        signal="rps",
        kind=SymptomKind.RESIDUAL_EXCEED,
        ts=33.0,
        score=0.1,
    )

    assert transitions[0].opened
    assert transitions[0].symptom.onset_ts == 0.0
    assert closed is not None and not closed.opened


def test_ratio_and_deploy_pass_through_emit_immediately():
    detector = SymptomDetector()
    ratio = detector.ratio(
        "auth-svc",
        RatioObservation(
            ts=10.0,
            signal="auth_fail_ratio",
            value=0.8,
            robust_z=7.0,
            score=0.9,
            deformed=True,
            onset_ts=0.0,
        ),
    )
    deploy = detector.deploy(
        DeployRecord(
            ts=11.0,
            service="payment-svc",
            commit="45d03f4c223f73f50eefac8d010b9f533cc4c69c",
            author="arjun",
            files=["payment_svc/retry.py"],
            summary="retry change",
        )
    )

    assert ratio is not None and ratio.symptom.kind is SymptomKind.RATIO_DEFORM
    assert deploy.symptom.kind is SymptomKind.DEPLOY_MARKER


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("log", SymptomKind.LOG_BURST),
        ("edge", SymptomKind.EDGE_DEGRADED),
        ("saturation", SymptomKind.SATURATION),
    ],
)
def test_remaining_symptom_kinds_use_same_sustained_gate(method, expected):
    detector = SymptomDetector()
    transition = None
    for ts in range(31):
        if method == "log":
            transition = detector.log_burst(
                service="payment-svc",
                template_id="TIMEOUT_DOWNSTREAM",
                ts=ts,
                score=0.9,
            )
        elif method == "edge":
            transition = detector.edge_degraded(
                TraceRecord(
                    ts=ts,
                    caller="payment-svc",
                    callee="notify-svc",
                    rps=100.0,
                    err_rate=0.4,
                    p99_ms=3000.0,
                ),
                score=0.9,
            )
        else:
            transition = detector.saturation(
                service="notify-svc",
                signal="queue_depth",
                ts=ts,
                score=0.9,
            )

    assert transition is not None
    assert transition.opened
    assert transition.symptom.kind is expected
