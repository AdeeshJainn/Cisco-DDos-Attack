"""P3.2 event-envelope and organic-ratio properties."""

from dataclasses import replace

import numpy as np
from argus.config import CONFIG
from argus.contracts import CalendarPhase
from argus.scenario.base import build_scenario_header, generate_base_load
from argus.scenario.events import (
    EventSpec,
    apply_events,
    calendar_records,
    event_envelope,
    generate_organic_net_features,
    iter_net_records,
)
from hypothesis import given
from hypothesis import strategies as st

SCORED_FROM_TS = 1789430400.0


def _event(multiplier: float = 4.0) -> EventSpec:
    return EventSpec(
        event_id="public-event",
        title="Public Event",
        announce_ts=SCORED_FROM_TS,
        ramp_start_ts=SCORED_FROM_TS + 10,
        peak_start_ts=SCORED_FROM_TS + 20,
        peak_end_ts=SCORED_FROM_TS + 40,
        end_ts=SCORED_FROM_TS + 50,
        multiplier=multiplier,
        affects=("edge-gw", "catalog-svc"),
    )


def _short_base(seed: int = 7):
    config = replace(CONFIG.scenario, warmup_hours=0, scenario_hours=1)
    header = build_scenario_header(
        seed=seed,
        profile="match_night",
        scored_from_ts=SCORED_FROM_TS,
        config=config,
    )
    return config, generate_base_load(np.random.default_rng(seed), header, config=config)


def test_trapezoid_envelope_has_baseline_ramp_plateau_and_decay():
    event = _event()
    ts = SCORED_FROM_TS + np.asarray([0, 10, 15, 20, 30, 40, 45, 50, 60])
    envelope = event_envelope(ts, event)

    assert np.allclose(envelope, [1.0, 1.0, 2.5, 4.0, 4.0, 4.0, 2.5, 1.0, 1.0])


def test_calendar_records_expose_all_event_phases_in_order():
    records = calendar_records(_event())

    assert [record.phase for record in records] == list(CalendarPhase)
    assert [record.ts for record in records] == sorted(record.ts for record in records)
    assert all(record.expected_multiplier == 4.0 for record in records)


def test_events_multiply_only_affected_services_and_recompute_pressure():
    config, base = _short_base()
    result = apply_events(base, [_event()], config=config)
    peak_index = 30

    assert np.isclose(result["edge-gw"].rps[peak_index], base["edge-gw"].rps[peak_index] * 4.0)
    assert np.isclose(
        result["catalog-svc"].rps[peak_index],
        base["catalog-svc"].rps[peak_index] * 4.0,
    )
    assert np.array_equal(result["auth-svc"].rps, base["auth-svc"].rps)
    assert result["catalog-svc"].p95_ms[peak_index] > base["catalog-svc"].p95_ms[peak_index]


@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    multiplier=st.floats(min_value=1.1, max_value=12.0, allow_nan=False),
)
def test_legitimate_multiplier_preserves_behavioral_ratios(seed: int, multiplier: float):
    config, base = _short_base(seed)
    edge = base["edge-gw"]
    organic = generate_organic_net_features(
        np.random.default_rng(seed),
        edge.service,
        edge.ts,
        config,
    )
    apply_events(base, [_event(multiplier)], config=config)

    regenerated = generate_organic_net_features(
        np.random.default_rng(seed),
        edge.service,
        edge.ts,
        config,
    )
    for field in (
        "uniq_ip_entropy",
        "syn_ack_ratio",
        "auth_fail_ratio",
        "ja3_novelty",
        "geo_top1_share",
    ):
        assert np.array_equal(getattr(organic, field), getattr(regenerated, field))


def test_net_record_adapter_emits_contract_valid_values():
    config, base = _short_base()
    edge = base["edge-gw"]
    organic = generate_organic_net_features(
        np.random.default_rng(11),
        edge.service,
        edge.ts,
        config,
    )
    record = next(iter_net_records(organic))

    assert record.service == "edge-gw"
    assert record.ts == SCORED_FROM_TS
    assert 0.0 <= record.auth_fail_ratio <= 1.0
    assert 0.0 <= record.ja3_novelty <= 1.0
