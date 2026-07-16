"""Attack overlays that deform behavior inside or outside legitimate events."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

import numpy as np

from argus.config import CONFIG, ScenarioConfig
from argus.contracts import ensure_ordered
from argus.scenario.base import (
    BaseLoadSeries,
    ServiceCapacity,
    derive_capacity_metrics,
    load_service_capacities,
)
from argus.scenario.events import NetFeatureSeries


class AttackType(StrEnum):
    VOLUMETRIC_FLOOD = "volumetric_flood"
    SYN_FLOOD = "syn_flood"
    APP_LAYER_FLOOD = "app_layer_flood"
    LOW_SLOW = "low_slow"


@dataclass(frozen=True)
class AttackSpec:
    """A generic attack window and suspect traffic cohort."""

    attack_id: str
    attack_type: AttackType
    start_ts: float
    end_ts: float
    target_service: str
    cohort: str
    intensity: float
    rps_multiplier: float

    def __post_init__(self) -> None:
        ensure_ordered([("start_ts", self.start_ts), ("end_ts", self.end_ts)])
        if self.end_ts == self.start_ts:
            raise ValueError("attack window must have positive duration")
        if not 0.0 < self.intensity <= 1.0:
            raise ValueError("attack intensity must be in (0, 1]")
        if self.rps_multiplier < 1.0:
            raise ValueError("attack rps_multiplier must be at least one")
        if not self.attack_id.strip() or not self.cohort.strip():
            raise ValueError("attack_id and cohort must be populated")


@dataclass(frozen=True)
class AttackResult:
    """Metrics, ratios and per-cohort attack contribution after overlays."""

    metrics: dict[str, BaseLoadSeries]
    network: dict[str, NetFeatureSeries]
    cohort_rps: dict[str, dict[str, np.ndarray]]


def attack_strength(
    ts: np.ndarray,
    attack: AttackSpec,
    config: ScenarioConfig = CONFIG.scenario,
) -> np.ndarray:
    """Return a 0..intensity ramp/hold/decay attack strength."""
    duration = attack.end_ts - attack.start_ts
    ramp_duration = min(duration / 2.0, duration * config.attack_ramp_fraction)
    plateau_start = attack.start_ts + ramp_duration
    plateau_end = attack.end_ts - ramp_duration
    strength = np.zeros(len(ts), dtype=np.float64)

    ramp = (ts >= attack.start_ts) & (ts < plateau_start)
    plateau = (ts >= plateau_start) & (ts <= plateau_end)
    decay = (ts > plateau_end) & (ts < attack.end_ts)
    if ramp_duration:
        strength[ramp] = attack.intensity * (ts[ramp] - attack.start_ts) / ramp_duration
        strength[decay] = attack.intensity * (attack.end_ts - ts[decay]) / ramp_duration
    strength[plateau] = attack.intensity
    return strength


def apply_attacks(
    metrics: dict[str, BaseLoadSeries],
    network: dict[str, NetFeatureSeries],
    attacks: list[AttackSpec],
    capacities: dict[str, ServiceCapacity] | None = None,
    config: ScenarioConfig = CONFIG.scenario,
) -> AttackResult:
    """Overlay attacks while retaining contribution by suppressible cohort."""
    capacities = capacities or load_service_capacities()
    unknown = {attack.target_service for attack in attacks} - set(metrics)
    if unknown:
        raise ValueError(f"attacks reference unknown services: {sorted(unknown)}")
    if set(metrics) != set(network):
        raise ValueError("metric and network services must match")

    result_metrics = dict(metrics)
    result_network = dict(network)
    cohort_rps: dict[str, dict[str, np.ndarray]] = {}

    for attack in attacks:
        service = attack.target_service
        current_metrics = result_metrics[service]
        current_network = result_network[service]
        strength = attack_strength(current_metrics.ts, attack, config)
        contribution = current_metrics.rps * (attack.rps_multiplier - 1.0) * strength
        cohort_rps.setdefault(attack.cohort, {})
        cohort_rps[attack.cohort][service] = (
            cohort_rps[attack.cohort].get(service, np.zeros(len(strength))) + contribution
        )

        rps = current_metrics.rps + contribution
        derived = derive_capacity_metrics(rps, capacities[service], config)
        updated_metrics = replace(current_metrics, rps=rps, **derived)
        updated_network = current_network

        if attack.attack_type is AttackType.VOLUMETRIC_FLOOD:
            updated_network = replace(
                current_network,
                uniq_ip_entropy=np.maximum(
                    current_network.uniq_ip_entropy - config.volumetric_entropy_drop * strength,
                    0.0,
                ),
                geo_top1_share=np.clip(
                    current_network.geo_top1_share + config.volumetric_geo_top1_gain * strength,
                    0.0,
                    1.0,
                ),
            )
        elif attack.attack_type is AttackType.SYN_FLOOD:
            updated_network = replace(
                current_network,
                syn_ack_ratio=(
                    current_network.syn_ack_ratio + config.syn_ack_ratio_gain * strength
                ),
            )
            updated_metrics = replace(
                updated_metrics,
                conn_active=updated_metrics.conn_active
                + capacities[service].max_conns * config.syn_connection_fraction_gain * strength,
                p95_ms=updated_metrics.p95_ms * (1.0 + config.syn_latency_gain * strength),
                p99_ms=updated_metrics.p99_ms * (1.0 + config.syn_latency_gain * strength),
            )
        elif attack.attack_type is AttackType.APP_LAYER_FLOOD:
            updated_network = replace(
                current_network,
                auth_fail_ratio=np.clip(
                    current_network.auth_fail_ratio + config.app_auth_fail_gain * strength,
                    0.0,
                    1.0,
                ),
                ja3_novelty=np.clip(
                    current_network.ja3_novelty + config.app_ja3_novelty_gain * strength,
                    0.0,
                    1.0,
                ),
                uniq_ip_entropy=np.maximum(
                    current_network.uniq_ip_entropy - config.app_entropy_drop * strength,
                    0.0,
                ),
            )
        elif attack.attack_type is AttackType.LOW_SLOW:
            updated_network = replace(
                current_network,
                ja3_novelty=np.clip(
                    current_network.ja3_novelty + config.low_slow_ja3_novelty_gain * strength,
                    0.0,
                    1.0,
                ),
            )
            updated_metrics = replace(
                updated_metrics,
                conn_active=updated_metrics.conn_active
                + capacities[service].max_conns
                * config.low_slow_connection_fraction_gain
                * strength,
                p99_ms=updated_metrics.p99_ms * (1.0 + config.low_slow_p99_gain * strength),
            )

        result_metrics[service] = updated_metrics
        result_network[service] = updated_network

    return AttackResult(
        metrics=result_metrics,
        network=result_network,
        cohort_rps=cohort_rps,
    )
