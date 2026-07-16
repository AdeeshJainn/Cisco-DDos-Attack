"""Fresh-seed and known-answer gates for the v0 detector/verdict path."""

from __future__ import annotations

import numpy as np
import pytest
from argus.contracts import (
    Incident,
    IncidentStatus,
    MetricName,
    Symptom,
    SymptomKind,
    VerdictClass,
)
from argus.detection.expected import SeasonalBaseline, expected_band
from argus.detection.ratios import RatioMonitor
from argus.detection.residual import decompose
from argus.detection.symptoms import SymptomDetector
from argus.scenario.attacks import AttackSpec, AttackType, apply_attacks
from argus.scenario.base import BaseLoadSeries, ServiceCapacity, derive_capacity_metrics
from argus.scenario.events import generate_organic_net_features
from argus.verdict.rules import classify

HELD_OUT_SEEDS = tuple(range(9100, 9120))


def _metric_series(ts: np.ndarray) -> tuple[BaseLoadSeries, ServiceCapacity]:
    capacity = ServiceCapacity(
        name="auth-svc",
        base_rps=100.0,
        capacity_rps=1000.0,
        max_conns=500.0,
        replicas=2,
    )
    rps = np.full(len(ts), capacity.base_rps)
    return (
        BaseLoadSeries(
            service=capacity.name,
            ts=ts,
            rps=rps,
            **derive_capacity_metrics(rps, capacity),
        ),
        capacity,
    )


@pytest.mark.parametrize("seed", HELD_OUT_SEEDS)
def test_quiet_behavior_never_opens_an_attack(seed: int):
    ts = np.arange(0.0, 360.0)
    network = generate_organic_net_features(
        np.random.Generator(np.random.PCG64(seed)),
        "auth-svc",
        ts,
    )
    monitor = RatioMonitor("auth_fail_ratio")

    assert not any(
        monitor.update(ts=float(now), value=float(value)).deformed
        for now, value in zip(ts, network.auth_fail_ratio, strict=True)
    )


@pytest.mark.parametrize("seed", HELD_OUT_SEEDS)
def test_nested_attack_detects_within_sixty_seconds_and_has_evidence(seed: int):
    ts = np.arange(0.0, 360.0)
    metrics, capacity = _metric_series(ts)
    network = generate_organic_net_features(
        np.random.Generator(np.random.PCG64(seed)),
        "auth-svc",
        ts,
    )
    attack = AttackSpec(
        attack_id="held-out-app-flood",
        attack_type=AttackType.APP_LAYER_FLOOD,
        start_ts=120.0,
        end_ts=240.0,
        target_service="auth-svc",
        cohort="untrusted-clients",
        intensity=0.85,
        rps_multiplier=2.5,
    )
    attacked = apply_attacks(
        {"auth-svc": metrics},
        {"auth-svc": network},
        [attack],
        {"auth-svc": capacity},
    )
    monitor = RatioMonitor("auth_fail_ratio")
    detected = None
    for now, value in zip(
        ts,
        attacked.network["auth-svc"].auth_fail_ratio,
        strict=True,
    ):
        observation = monitor.update(ts=float(now), value=float(value))
        if observation.deformed:
            detected = observation
            break

    assert detected is not None
    assert detected.ts - attack.start_ts <= 60.0
    symptom = Symptom(
        service="auth-svc",
        signal=detected.signal,
        kind=SymptomKind.RATIO_DEFORM,
        onset_ts=detected.onset_ts or detected.ts,
        score=detected.score,
    )
    verdict = classify(
        Incident(
            incident_id=f"held-out-{seed}",
            status=IncidentStatus.OPEN,
            first_ts=symptom.onset_ts,
            last_ts=detected.ts,
            symptoms=[symptom],
        )
    )
    top_class = max(verdict.classes, key=lambda item: item.p).verdict_class

    assert top_class is VerdictClass.ATTACK
    assert verdict.evidence


def _known_answer_frames(shape: str):
    history_ts = np.arange(0.0, 2 * 86400.0, 60.0)
    history = 100.0 + 8.0 * np.sin(2.0 * np.pi * history_ts / 86400.0)
    baseline = SeasonalBaseline.fit(history_ts, history)
    ts = 2 * 86400.0 + np.arange(0.0, 120.0)
    band = expected_band(baseline, ts, service="edge-gw", events=[])
    observed = band.base.copy()
    if shape == "step":
        observed[30:] += 5.0 * band.half_width[30:]
    elif shape == "ramp":
        observed += np.linspace(0.0, 5.0, len(ts)) * band.half_width
    elif shape == "spike":
        observed[60] += 5.0 * band.half_width[60]
    else:
        raise AssertionError(shape)
    return list(
        decompose(
            ts=ts,
            observed=observed,
            service="edge-gw",
            signal=MetricName.RPS,
            baseline=baseline,
            events=[],
        )
    )


@pytest.mark.parametrize(
    ("shape", "opens"),
    [("step", True), ("ramp", True), ("spike", False)],
)
def test_step_ramp_and_spike_have_expected_sustained_gate(shape: str, opens: bool):
    detector = SymptomDetector()
    transitions = [
        transition
        for frame in _known_answer_frames(shape)
        if (transition := detector.residual(frame)) is not None and transition.opened
    ]

    assert bool(transitions) is opens
