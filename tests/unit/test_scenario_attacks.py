"""P3.3 attack signatures, nesting and cohort bookkeeping."""

from dataclasses import replace

import numpy as np
import pytest
from argus.config import CONFIG
from argus.scenario.attacks import AttackSpec, AttackType, apply_attacks
from argus.scenario.base import build_scenario_header, generate_base_load
from argus.scenario.events import (
    EventSpec,
    apply_events,
    generate_organic_net_features,
)

SCORED_FROM_TS = 1789430400.0


@pytest.fixture()
def world():
    config = replace(CONFIG.scenario, warmup_hours=0, scenario_hours=1)
    header = build_scenario_header(
        seed=21,
        profile="combo_night",
        scored_from_ts=SCORED_FROM_TS,
        config=config,
    )
    base = generate_base_load(np.random.default_rng(21), header, config=config)
    event = EventSpec(
        event_id="event",
        title="Legitimate Event",
        announce_ts=SCORED_FROM_TS,
        ramp_start_ts=SCORED_FROM_TS + 100,
        peak_start_ts=SCORED_FROM_TS + 200,
        peak_end_ts=SCORED_FROM_TS + 800,
        end_ts=SCORED_FROM_TS + 900,
        multiplier=5.0,
        affects=("edge-gw", "auth-svc", "catalog-svc"),
    )
    metrics = apply_events(base, [event], config=config)
    network = {
        service: generate_organic_net_features(
            np.random.default_rng(100 + index),
            service,
            series.ts,
            config,
        )
        for index, (service, series) in enumerate(metrics.items())
    }
    return config, metrics, network


def _attack(
    attack_type: AttackType,
    *,
    target: str = "edge-gw",
    multiplier: float = 2.0,
) -> AttackSpec:
    return AttackSpec(
        attack_id=f"attack-{attack_type}",
        attack_type=attack_type,
        start_ts=SCORED_FROM_TS + 300,
        end_ts=SCORED_FROM_TS + 500,
        target_service=target,
        cohort="suspect-clients",
        intensity=1.0,
        rps_multiplier=multiplier,
    )


def test_volumetric_flood_deforms_entropy_and_geo_inside_event(world):
    config, metrics, network = world
    result = apply_attacks(
        metrics,
        network,
        [_attack(AttackType.VOLUMETRIC_FLOOD, multiplier=4.0)],
        config=config,
    )
    index = 400

    assert result.metrics["edge-gw"].rps[index] > metrics["edge-gw"].rps[index]
    assert (
        result.network["edge-gw"].uniq_ip_entropy[index] < network["edge-gw"].uniq_ip_entropy[index]
    )
    assert (
        result.network["edge-gw"].geo_top1_share[index] > network["edge-gw"].geo_top1_share[index]
    )
    assert np.array_equal(
        result.network["edge-gw"].uniq_ip_entropy[:300],
        network["edge-gw"].uniq_ip_entropy[:300],
    )


def test_syn_flood_deforms_handshakes_connections_and_latency(world):
    config, metrics, network = world
    result = apply_attacks(
        metrics,
        network,
        [_attack(AttackType.SYN_FLOOD, multiplier=1.2)],
        config=config,
    )
    index = 400

    assert result.network["edge-gw"].syn_ack_ratio[index] > 5.0
    assert result.metrics["edge-gw"].conn_active[index] > metrics["edge-gw"].conn_active[index]
    assert result.metrics["edge-gw"].p99_ms[index] > metrics["edge-gw"].p99_ms[index]


def test_app_layer_flood_deforms_auth_ja3_and_entropy(world):
    config, metrics, network = world
    result = apply_attacks(
        metrics,
        network,
        [_attack(AttackType.APP_LAYER_FLOOD, target="auth-svc", multiplier=3.0)],
        config=config,
    )
    index = 400

    assert result.network["auth-svc"].auth_fail_ratio[index] > 0.5
    assert result.network["auth-svc"].ja3_novelty[index] > 0.5
    assert (
        result.network["auth-svc"].uniq_ip_entropy[index]
        < network["auth-svc"].uniq_ip_entropy[index]
    )


def test_low_slow_is_visible_without_meaningful_volume(world):
    config, metrics, network = world
    result = apply_attacks(
        metrics,
        network,
        [_attack(AttackType.LOW_SLOW, multiplier=1.0)],
        config=config,
    )
    index = 400

    assert result.metrics["edge-gw"].rps[index] == metrics["edge-gw"].rps[index]
    assert result.metrics["edge-gw"].conn_active[index] > metrics["edge-gw"].conn_active[index]
    assert result.metrics["edge-gw"].p99_ms[index] > metrics["edge-gw"].p99_ms[index]
    assert result.network["edge-gw"].ja3_novelty[index] > 0.4


def test_cohort_contribution_exactly_accounts_for_attack_rps(world):
    config, metrics, network = world
    result = apply_attacks(
        metrics,
        network,
        [_attack(AttackType.VOLUMETRIC_FLOOD, multiplier=4.0)],
        config=config,
    )
    delta = result.metrics["edge-gw"].rps - metrics["edge-gw"].rps

    assert np.allclose(
        result.cohort_rps["suspect-clients"]["edge-gw"],
        delta,
    )
