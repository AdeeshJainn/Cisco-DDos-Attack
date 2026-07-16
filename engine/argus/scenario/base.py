"""Seeded base demand and generic capacity-derived service telemetry."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from argus import CONTRACT_VERSION
from argus.config import CONFIG, ScenarioConfig
from argus.contracts import MetricName, MetricRecord, ScenarioHeader

SECONDS_PER_HOUR = 60 * 60
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR
EPOCH_WEEKDAY = 3  # 1970-01-01 was Thursday when Monday is index zero.
DEFAULT_TOPOLOGY_PATH = Path(__file__).resolve().parents[3] / "demo-app" / "topology.yaml"


@dataclass(frozen=True)
class ServiceCapacity:
    """Scenario-facing subset of one topology service declaration."""

    name: str
    base_rps: float
    capacity_rps: float
    max_conns: float
    replicas: int


@dataclass(frozen=True)
class BaseLoadSeries:
    """All required metric signals for one service on the shared clock."""

    service: str
    ts: np.ndarray
    rps: np.ndarray
    err_rate: np.ndarray
    p50_ms: np.ndarray
    p95_ms: np.ndarray
    p99_ms: np.ndarray
    cpu_pct: np.ndarray
    mem_pct: np.ndarray
    conn_active: np.ndarray
    queue_depth: np.ndarray

    def __post_init__(self) -> None:
        lengths = {
            len(self.ts),
            len(self.rps),
            len(self.err_rate),
            len(self.p50_ms),
            len(self.p95_ms),
            len(self.p99_ms),
            len(self.cpu_pct),
            len(self.mem_pct),
            len(self.conn_active),
            len(self.queue_depth),
        }
        if len(lengths) != 1:
            raise ValueError("all base-load arrays must share one clock")


def load_service_capacities(
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
) -> dict[str, ServiceCapacity]:
    """Load per-service demand and capacity from the single world model."""
    with topology_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    capacities: dict[str, ServiceCapacity] = {}
    for name, spec in raw["services"].items():
        capacity = ServiceCapacity(
            name=name,
            base_rps=float(spec["base_rps"]),
            capacity_rps=float(spec["capacity_rps"]),
            max_conns=float(spec["max_conns"]),
            replicas=int(spec["replicas"]),
        )
        if capacity.base_rps <= 0 or capacity.capacity_rps <= capacity.base_rps:
            raise ValueError(f"{name}: topology must provide positive capacity headroom")
        if capacity.max_conns <= 0 or capacity.replicas < 1:
            raise ValueError(f"{name}: invalid connection or replica capacity")
        capacities[name] = capacity
    if not capacities:
        raise ValueError("topology declares no services")
    return capacities


def build_scenario_header(
    *,
    seed: int,
    profile: str,
    scored_from_ts: float,
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
    config: ScenarioConfig = CONFIG.scenario,
) -> ScenarioHeader:
    """Build a frozen-contract header with deterministic warmup boundaries."""
    capacities = load_service_capacities(topology_path)
    start_ts = scored_from_ts - config.warmup_hours * SECONDS_PER_HOUR
    end_ts = scored_from_ts + config.scenario_hours * SECONDS_PER_HOUR
    return ScenarioHeader(
        contract=CONTRACT_VERSION,
        seed=seed,
        profile=profile,
        start_ts=start_ts,
        scored_from_ts=scored_from_ts,
        end_ts=end_ts,
        resolution_s=config.resolution_s,
        warmup_resolution_s=config.warmup_resolution_s,
        services=list(capacities),
        demo_app_manifest=".manifest.lock.json",
    )


def scenario_timestamps(header: ScenarioHeader) -> np.ndarray:
    """Return the warmup and scored clocks without duplicating the boundary."""
    warmup = np.arange(
        header.start_ts,
        header.scored_from_ts,
        header.warmup_resolution_s,
        dtype=np.float64,
    )
    scored = np.arange(
        header.scored_from_ts,
        header.end_ts,
        header.resolution_s,
        dtype=np.float64,
    )
    return np.concatenate((warmup, scored))


def _calendar_shape(ts: np.ndarray, config: ScenarioConfig) -> np.ndarray:
    hour = np.mod(ts, SECONDS_PER_DAY) / SECONDS_PER_HOUR
    angle = 2.0 * np.pi * (hour - config.diurnal_peak_hour_utc) / 24.0
    diurnal = (
        config.diurnal_floor
        + config.diurnal_primary_amplitude * np.cos(angle)
        + config.diurnal_secondary_amplitude * np.cos(2.0 * angle)
    )
    day_number = np.floor_divide(ts.astype(np.int64), SECONDS_PER_DAY)
    weekday = np.mod(day_number + EPOCH_WEEKDAY, len(config.weekly_multipliers))
    weekly = np.take(np.asarray(config.weekly_multipliers), weekday)
    return diurnal * weekly


def _ar1_noise(
    rng: np.random.Generator,
    ts: np.ndarray,
    config: ScenarioConfig,
) -> np.ndarray:
    """Generate a stationary AR(1) process with coefficients scaled by dt."""
    noise = np.empty(len(ts), dtype=np.float64)
    if not len(ts):
        return noise
    noise[0] = rng.normal(0.0, config.ar1_sigma_fraction)
    for index in range(1, len(ts)):
        elapsed_minutes = (ts[index] - ts[index - 1]) / 60.0
        phi = config.ar1_phi_per_minute**elapsed_minutes
        innovation_sigma = config.ar1_sigma_fraction * np.sqrt(max(0.0, 1.0 - phi**2))
        noise[index] = phi * noise[index - 1] + rng.normal(0.0, innovation_sigma)
    return noise


def derive_capacity_metrics(
    rps: np.ndarray,
    service: ServiceCapacity,
    config: ScenarioConfig = CONFIG.scenario,
) -> dict[str, np.ndarray]:
    """Map demand to latency, saturation, resource, queue and error signals."""
    demand = np.maximum(np.asarray(rps, dtype=np.float64), 0.0)
    utilization = demand / service.capacity_rps
    pressure = np.maximum(utilization - config.capacity_knee_utilization, 0.0) / (
        1.0 - config.capacity_knee_utilization
    )

    latency_factor = (
        1.0 + config.latency_util_gain * utilization + config.latency_pressure_gain * pressure**2
    )
    p50_ms = config.latency_floor_ms * latency_factor
    p95_ms = p50_ms * config.p95_multiplier
    p99_ms = p50_ms * config.p99_multiplier
    cpu_pct = np.clip(
        config.idle_cpu_pct
        + config.cpu_util_gain_pct * utilization
        + config.cpu_pressure_gain_pct * pressure**2,
        0.0,
        100.0,
    )
    mem_pct = np.clip(
        config.idle_mem_pct
        + config.mem_util_gain_pct * np.sqrt(utilization)
        + config.mem_pressure_gain_pct * pressure,
        0.0,
        100.0,
    )
    conn_active = np.minimum(
        service.max_conns * (1.0 + pressure),
        service.max_conns * config.idle_connection_fraction
        + demand * (p95_ms / 1000.0) * config.connection_latency_weight
        + service.max_conns * config.connection_pressure_fraction * pressure,
    )
    queue_depth = (
        np.maximum(
            demand - service.capacity_rps * config.capacity_knee_utilization,
            0.0,
        )
        * config.queue_drain_window_s
        * (1.0 + pressure)
    )
    overload = np.maximum(utilization - 1.0, 0.0)
    err_rate = np.clip(
        config.baseline_error_rate + config.overload_error_gain * overload**2,
        0.0,
        1.0,
    )
    return {
        "err_rate": err_rate,
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "p99_ms": p99_ms,
        "cpu_pct": cpu_pct,
        "mem_pct": mem_pct,
        "conn_active": conn_active,
        "queue_depth": queue_depth,
    }


def generate_base_load(
    rng: np.random.Generator,
    header: ScenarioHeader,
    *,
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
    config: ScenarioConfig = CONFIG.scenario,
) -> dict[str, BaseLoadSeries]:
    """Generate deterministic per-service demand using one threaded RNG."""
    capacities = load_service_capacities(topology_path)
    if list(capacities) != header.services:
        raise ValueError("scenario header services do not match topology order")
    ts = scenario_timestamps(header)
    calendar_shape = _calendar_shape(ts, config)

    series: dict[str, BaseLoadSeries] = {}
    for service in capacities.values():
        noise = _ar1_noise(rng, ts, config)
        load_factor = np.maximum(
            calendar_shape * (1.0 + noise),
            config.minimum_load_factor,
        )
        rps = service.base_rps * load_factor
        metrics = derive_capacity_metrics(rps, service, config)
        series[service.name] = BaseLoadSeries(
            service=service.name,
            ts=ts,
            rps=rps,
            **metrics,
        )
    return series


_METRIC_ARRAYS: tuple[tuple[MetricName, str], ...] = (
    (MetricName.RPS, "rps"),
    (MetricName.ERR_RATE, "err_rate"),
    (MetricName.P50_MS, "p50_ms"),
    (MetricName.P95_MS, "p95_ms"),
    (MetricName.P99_MS, "p99_ms"),
    (MetricName.CPU_PCT, "cpu_pct"),
    (MetricName.MEM_PCT, "mem_pct"),
    (MetricName.CONN_ACTIVE, "conn_active"),
    (MetricName.QUEUE_DEPTH, "queue_depth"),
)


def iter_metric_records(series: BaseLoadSeries) -> Iterator[MetricRecord]:
    """Yield frozen-contract metric records in timestamp then metric order."""
    for index, ts in enumerate(series.ts):
        for name, attribute in _METRIC_ARRAYS:
            values = getattr(series, attribute)
            yield MetricRecord(
                ts=float(ts),
                service=series.service,
                name=name,
                value=float(values[index]),
            )
