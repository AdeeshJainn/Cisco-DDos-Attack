"""P3.1 base-load determinism, warmup and capacity-model tests."""

from dataclasses import replace

import numpy as np
from argus.config import CONFIG
from argus.contracts import MetricName
from argus.scenario.base import (
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    ServiceCapacity,
    build_scenario_header,
    derive_capacity_metrics,
    generate_base_load,
    iter_metric_records,
    load_service_capacities,
    scenario_timestamps,
)

SCORED_FROM_TS = 1789430400.0


def _small_config():
    return replace(CONFIG.scenario, warmup_hours=2, scenario_hours=1)


def test_header_and_clock_include_48_hour_warmup_then_24_scored_hours():
    header = build_scenario_header(
        seed=42,
        profile="quiet_day",
        scored_from_ts=SCORED_FROM_TS,
    )
    timestamps = scenario_timestamps(header)

    assert header.start_ts == SCORED_FROM_TS - 2 * SECONDS_PER_DAY
    assert header.end_ts == SCORED_FROM_TS + SECONDS_PER_DAY
    assert timestamps[0] == header.start_ts
    assert timestamps[-1] == header.end_ts - header.resolution_s
    assert np.sum(timestamps < header.scored_from_ts) == 48 * 60
    assert np.sum(timestamps >= header.scored_from_ts) == 24 * SECONDS_PER_HOUR
    assert np.all(np.diff(timestamps[: 48 * 60]) == header.warmup_resolution_s)
    assert np.all(np.diff(timestamps[48 * 60 :]) == header.resolution_s)


def test_base_load_is_seed_deterministic_and_seed_sensitive():
    config = _small_config()
    header = build_scenario_header(
        seed=17,
        profile="quiet_day",
        scored_from_ts=SCORED_FROM_TS,
        config=config,
    )
    first = generate_base_load(np.random.default_rng(17), header, config=config)
    second = generate_base_load(np.random.default_rng(17), header, config=config)
    other = generate_base_load(np.random.default_rng(18), header, config=config)

    assert first.keys() == second.keys()
    for service in first:
        assert np.array_equal(first[service].rps, second[service].rps)
    assert not np.array_equal(first["edge-gw"].rps, other["edge-gw"].rps)


def test_topology_controls_per_service_scale_and_capacity():
    config = replace(
        _small_config(),
        ar1_sigma_fraction=0.0,
        weekly_multipliers=(1.0,) * 7,
    )
    header = build_scenario_header(
        seed=1,
        profile="quiet_day",
        scored_from_ts=SCORED_FROM_TS + 15 * SECONDS_PER_HOUR,
        config=config,
    )
    series = generate_base_load(np.random.default_rng(1), header, config=config)
    capacities = load_service_capacities()

    peak_offset = int(config.diurnal_peak_hour_utc * SECONDS_PER_HOUR)
    peak_indices = np.flatnonzero(np.mod(series["edge-gw"].ts, SECONDS_PER_DAY) == peak_offset)
    assert len(peak_indices)
    index = int(peak_indices[0])
    for service, spec in capacities.items():
        assert np.isclose(series[service].rps[index], spec.base_rps)
        assert np.all(series[service].rps > 0)


def test_capacity_metrics_knee_and_overload_are_monotonic():
    service = ServiceCapacity(
        name="test-svc",
        base_rps=100.0,
        capacity_rps=1000.0,
        max_conns=500.0,
        replicas=2,
    )
    demand = np.asarray([400.0, 800.0, 1000.0, 1200.0])
    metrics = derive_capacity_metrics(demand, service)

    for name in (
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "cpu_pct",
        "mem_pct",
        "conn_active",
    ):
        assert np.all(np.diff(metrics[name]) >= 0), name
    assert metrics["queue_depth"][0] == 0
    assert metrics["queue_depth"][1] == 0
    assert metrics["queue_depth"][3] > metrics["queue_depth"][2] > 0
    assert metrics["err_rate"][0] == CONFIG.scenario.baseline_error_rate
    assert metrics["err_rate"][2] == CONFIG.scenario.baseline_error_rate
    assert metrics["err_rate"][3] > metrics["err_rate"][2]


def test_metric_record_adapter_emits_all_required_names_in_order():
    config = replace(_small_config(), warmup_hours=0, scenario_hours=1)
    header = build_scenario_header(
        seed=9,
        profile="quiet_day",
        scored_from_ts=SCORED_FROM_TS,
        config=config,
    )
    series = generate_base_load(np.random.default_rng(9), header, config=config)["edge-gw"]
    first_tick = [record for _, record in zip(range(9), iter_metric_records(series), strict=False)]

    assert [record.name for record in first_tick] == list(MetricName)
    assert {record.service for record in first_tick} == {"edge-gw"}
    assert {record.ts for record in first_tick} == {SCORED_FROM_TS}
