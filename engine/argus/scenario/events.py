"""Event calendar and ratio-preserving legitimate surge envelopes."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace

import numpy as np

from argus.config import CONFIG, ScenarioConfig
from argus.contracts import CalendarPhase, CalendarRecord, NetRecord, ensure_ordered
from argus.scenario.base import (
    BaseLoadSeries,
    ServiceCapacity,
    derive_capacity_metrics,
    load_service_capacities,
)


@dataclass(frozen=True)
class EventSpec:
    """One legitimate event with a trapezoid demand envelope."""

    event_id: str
    title: str
    announce_ts: float
    ramp_start_ts: float
    peak_start_ts: float
    peak_end_ts: float
    end_ts: float
    multiplier: float
    affects: tuple[str, ...]

    def __post_init__(self) -> None:
        ensure_ordered(
            [
                ("announce_ts", self.announce_ts),
                ("ramp_start_ts", self.ramp_start_ts),
                ("peak_start_ts", self.peak_start_ts),
                ("peak_end_ts", self.peak_end_ts),
                ("end_ts", self.end_ts),
            ]
        )
        if self.multiplier <= 1.0:
            raise ValueError("event multiplier must exceed one")
        if not self.event_id.strip() or not self.affects:
            raise ValueError("event_id and affects must be populated")


@dataclass(frozen=True)
class NetFeatureSeries:
    """Organic behavior ratios on the same clock as service metrics."""

    service: str
    ts: np.ndarray
    uniq_ip_entropy: np.ndarray
    syn_ack_ratio: np.ndarray
    auth_fail_ratio: np.ndarray
    ja3_novelty: np.ndarray
    geo_top1_share: np.ndarray

    def __post_init__(self) -> None:
        lengths = {
            len(self.ts),
            len(self.uniq_ip_entropy),
            len(self.syn_ack_ratio),
            len(self.auth_fail_ratio),
            len(self.ja3_novelty),
            len(self.geo_top1_share),
        }
        if len(lengths) != 1:
            raise ValueError("all network-feature arrays must share one clock")


def event_envelope(ts: np.ndarray, event: EventSpec) -> np.ndarray:
    """Return a baseline-one ramp, plateau and decay multiplier."""
    values = np.ones(len(ts), dtype=np.float64)
    ramp = (ts >= event.ramp_start_ts) & (ts < event.peak_start_ts)
    peak = (ts >= event.peak_start_ts) & (ts <= event.peak_end_ts)
    decay = (ts > event.peak_end_ts) & (ts < event.end_ts)

    ramp_duration = event.peak_start_ts - event.ramp_start_ts
    if ramp_duration:
        progress = (ts[ramp] - event.ramp_start_ts) / ramp_duration
        values[ramp] = 1.0 + (event.multiplier - 1.0) * progress
    values[peak] = event.multiplier
    decay_duration = event.end_ts - event.peak_end_ts
    if decay_duration:
        progress = (ts[decay] - event.peak_end_ts) / decay_duration
        values[decay] = event.multiplier - (event.multiplier - 1.0) * progress
    return values


def calendar_records(event: EventSpec) -> list[CalendarRecord]:
    """Expose event context as frozen-contract calendar markers."""
    peak_marker_ts = event.peak_start_ts + (event.peak_end_ts - event.peak_start_ts) / 2.0
    phases = (
        (event.announce_ts, CalendarPhase.ANNOUNCE),
        (event.ramp_start_ts, CalendarPhase.RAMP),
        (event.peak_start_ts, CalendarPhase.START),
        (peak_marker_ts, CalendarPhase.PEAK),
        (event.end_ts, CalendarPhase.END),
    )
    return [
        CalendarRecord(
            ts=ts,
            event_id=event.event_id,
            title=event.title,
            phase=phase,
            expected_multiplier=event.multiplier,
            affects=list(event.affects),
        )
        for ts, phase in phases
    ]


def generate_organic_net_features(
    rng: np.random.Generator,
    service: str,
    ts: np.ndarray,
    config: ScenarioConfig = CONFIG.scenario,
) -> NetFeatureSeries:
    """Generate seeded load-invariant behavior features for organic users."""

    def jittered(center: float, jitter: float, *, lower: float, upper: float) -> np.ndarray:
        return np.clip(center + rng.normal(0.0, jitter, len(ts)), lower, upper)

    return NetFeatureSeries(
        service=service,
        ts=ts,
        uniq_ip_entropy=jittered(
            config.organic_uniq_ip_entropy,
            config.organic_uniq_ip_entropy_jitter,
            lower=0.0,
            upper=np.inf,
        ),
        syn_ack_ratio=jittered(
            config.organic_syn_ack_ratio,
            config.organic_syn_ack_ratio_jitter,
            lower=0.0,
            upper=np.inf,
        ),
        auth_fail_ratio=jittered(
            config.organic_auth_fail_ratio,
            config.organic_auth_fail_ratio_jitter,
            lower=0.0,
            upper=1.0,
        ),
        ja3_novelty=jittered(
            config.organic_ja3_novelty,
            config.organic_ja3_novelty_jitter,
            lower=0.0,
            upper=1.0,
        ),
        geo_top1_share=jittered(
            config.organic_geo_top1_share,
            config.organic_geo_top1_share_jitter,
            lower=0.0,
            upper=1.0,
        ),
    )


def apply_events(
    base: dict[str, BaseLoadSeries],
    events: list[EventSpec],
    capacities: dict[str, ServiceCapacity] | None = None,
    config: ScenarioConfig = CONFIG.scenario,
) -> dict[str, BaseLoadSeries]:
    """Apply all legitimate volume envelopes and recompute derived metrics."""
    capacities = capacities or load_service_capacities()
    unknown = {service for event in events for service in event.affects} - set(base)
    if unknown:
        raise ValueError(f"events reference unknown services: {sorted(unknown)}")

    result: dict[str, BaseLoadSeries] = {}
    for service, series in base.items():
        combined = np.ones(len(series.ts), dtype=np.float64)
        for event in events:
            if service in event.affects:
                combined *= event_envelope(series.ts, event)
        rps = series.rps * combined
        result[service] = replace(
            series,
            rps=rps,
            **derive_capacity_metrics(rps, capacities[service], config),
        )
    return result


def iter_net_records(series: NetFeatureSeries) -> Iterator[NetRecord]:
    """Yield contract-valid network behavior records."""
    for index, ts in enumerate(series.ts):
        yield NetRecord(
            ts=float(ts),
            service=series.service,
            uniq_ip_entropy=float(series.uniq_ip_entropy[index]),
            syn_ack_ratio=float(series.syn_ack_ratio[index]),
            auth_fail_ratio=float(series.auth_fail_ratio[index]),
            ja3_novelty=float(series.ja3_novelty[index]),
            geo_top1_share=float(series.geo_top1_share[index]),
        )
