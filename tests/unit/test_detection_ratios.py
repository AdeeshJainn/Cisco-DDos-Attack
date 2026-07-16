"""P4.2 behavioral-ratio robust-z and hysteresis tests."""

import numpy as np
from argus.detection.ratios import RatioMonitor


def _warm(monitor: RatioMonitor, center: float = 1.0) -> float:
    rng = np.random.default_rng(7)
    ts = 0.0
    for value in center + rng.normal(0.0, 0.01, 60):
        monitor.update(ts=ts, value=float(value))
        ts += 1.0
    return ts


def test_sustained_deformation_opens_after_30_seconds():
    monitor = RatioMonitor("syn_ack_ratio")
    ts = _warm(monitor)
    observations = [monitor.update(ts=ts + offset, value=2.0) for offset in range(32)]

    assert not observations[29].deformed
    assert observations[30].deformed
    assert observations[30].onset_ts == ts
    assert observations[30].score > 0.5


def test_release_hysteresis_closes_on_return_inside_two_sigma():
    monitor = RatioMonitor("auth_fail_ratio")
    ts = _warm(monitor, center=0.02)
    for offset in range(31):
        opened = monitor.update(ts=ts + offset, value=0.5)
    assert opened.deformed

    released = monitor.update(ts=ts + 32, value=0.02, incident_open=True)
    assert not released.deformed
    assert released.onset_ts is None


def test_open_incident_values_do_not_poison_clean_baseline():
    monitor = RatioMonitor("ja3_novelty")
    ts = _warm(monitor, center=0.03)
    for offset in range(120):
        monitor.update(ts=ts + offset, value=0.9, incident_open=True)

    observation = monitor.update(ts=ts + 121, value=0.03, incident_open=True)
    assert abs(observation.robust_z) < 2.0


def test_short_spike_never_opens_incident():
    monitor = RatioMonitor("uniq_ip_entropy")
    ts = _warm(monitor, center=7.8)
    observations = [monitor.update(ts=ts + offset, value=4.0) for offset in range(10)]

    assert not any(observation.deformed for observation in observations)
