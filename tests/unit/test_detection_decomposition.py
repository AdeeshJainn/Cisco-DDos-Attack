"""P4.1 robust seasonal band and surge decomposition tests."""

import numpy as np
from argus.contracts import MetricName
from argus.detection.expected import SeasonalBaseline, expected_band
from argus.detection.residual import DecompStore, decompose
from argus.scenario.base import SECONDS_PER_DAY
from argus.scenario.events import EventSpec


def _history():
    minute = 60.0
    ts = np.concatenate(
        (
            np.arange(0.0, SECONDS_PER_DAY, minute),
            np.arange(SECONDS_PER_DAY, 2 * SECONDS_PER_DAY, minute),
        )
    )
    values = 100.0 + 20.0 * np.sin(2.0 * np.pi * ts / SECONDS_PER_DAY)
    return ts, values


def _event(start: float) -> EventSpec:
    return EventSpec(
        event_id="event",
        title="Event",
        announce_ts=start,
        ramp_start_ts=start,
        peak_start_ts=start + 60,
        peak_end_ts=start + 180,
        end_ts=start + 240,
        multiplier=4.0,
        affects=("edge-gw",),
    )


def test_seasonal_baseline_recovers_same_time_of_day():
    ts, values = _history()
    baseline = SeasonalBaseline.fit(ts, values)
    query = np.asarray([2 * SECONDS_PER_DAY + 6 * 3600])
    predicted, _ = baseline.predict(query)

    assert np.isclose(predicted[0], 120.0)


def test_event_volume_is_explained_without_residual():
    ts, values = _history()
    baseline = SeasonalBaseline.fit(ts, values)
    query = 2 * SECONDS_PER_DAY + np.arange(0.0, 300.0, 60.0)
    event = _event(query[0])
    band = expected_band(baseline, query, service="edge-gw", events=[event])
    observed = band.base + band.event
    frames = list(
        decompose(
            ts=query,
            observed=observed,
            service="edge-gw",
            signal=MetricName.RPS,
            baseline=baseline,
            events=[event],
        )
    )

    assert max(abs(frame.residual) for frame in frames) < 1e-9
    assert max(frame.residual_score for frame in frames) == 0.0
    assert frames[2].explained_event > 0


def test_unexplained_attack_rides_above_event_band():
    ts, values = _history()
    baseline = SeasonalBaseline.fit(ts, values)
    query = 2 * SECONDS_PER_DAY + np.arange(0.0, 300.0, 60.0)
    event = _event(query[0])
    band = expected_band(baseline, query, service="edge-gw", events=[event])
    observed = band.base + band.event
    observed[2] += 5.0 * band.half_width[2]
    frames = list(
        decompose(
            ts=query,
            observed=observed,
            service="edge-gw",
            signal=MetricName.RPS,
            baseline=baseline,
            events=[event],
        )
    )

    assert frames[2].residual > 0
    assert frames[2].residual_score == 1.0


def test_decomp_store_downsamples_and_keeps_endpoints():
    ts, values = _history()
    baseline = SeasonalBaseline.fit(ts, values)
    query = np.arange(0.0, 600.0, 60.0)
    frames = list(
        decompose(
            ts=query,
            observed=values[: len(query)],
            service="edge-gw",
            signal=MetricName.RPS,
            baseline=baseline,
            events=[],
        )
    )
    store = DecompStore()
    store.add(iter(frames))
    selected = store.query(
        service="edge-gw",
        signal=MetricName.RPS,
        from_ts=0.0,
        to_ts=600.0,
        max_points=4,
    )

    assert len(selected) == 4
    assert selected[0].ts == frames[0].ts
    assert selected[-1].ts == frames[-1].ts
