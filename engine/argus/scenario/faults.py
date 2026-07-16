"""Mechanistic fault cascades tied to real demo-app commits."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

import numpy as np
import yaml

from argus.config import CONFIG, ScenarioConfig
from argus.contracts import DeployRecord, LogRecord, TraceRecord, ensure_ordered
from argus.scenario.base import (
    DEFAULT_TOPOLOGY_PATH,
    BaseLoadSeries,
    ServiceCapacity,
    derive_capacity_metrics,
    load_service_capacities,
)

DEFAULT_MANIFEST_LOCK_PATH = (
    Path(__file__).resolve().parents[3] / "demo-app" / ".manifest.lock.json"
)


@dataclass(frozen=True)
class FaultCatalogEntry:
    fault_id: str
    sub_type: str
    mechanism: str
    commit: str
    fix_commit: str
    file: str
    line: int
    function: str
    pattern: str
    service: str
    author: str
    summary: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class FaultSpec:
    fault_id: str
    deploy_ts: float
    onset_ts: float
    end_ts: float
    severity: float

    def __post_init__(self) -> None:
        ensure_ordered(
            [
                ("deploy_ts", self.deploy_ts),
                ("onset_ts", self.onset_ts),
                ("end_ts", self.end_ts),
            ]
        )
        if self.onset_ts == self.end_ts:
            raise ValueError("fault window must have positive duration")
        if not 0.0 < self.severity <= 1.0:
            raise ValueError("fault severity must be in (0, 1]")


class OperationalFaultType(StrEnum):
    LINK_BROWNOUT = "link_brownout"
    CAPACITY_LOSS = "capacity_loss"


@dataclass(frozen=True)
class OperationalFaultSpec:
    fault_id: str
    fault_type: OperationalFaultType
    onset_ts: float
    end_ts: float
    severity: float
    service: str | None = None
    caller: str | None = None
    callee: str | None = None

    def __post_init__(self) -> None:
        ensure_ordered([("onset_ts", self.onset_ts), ("end_ts", self.end_ts)])
        if self.onset_ts == self.end_ts:
            raise ValueError("operational fault window must have positive duration")
        if not 0.0 < self.severity <= 1.0:
            raise ValueError("operational fault severity must be in (0, 1]")
        if self.fault_type is OperationalFaultType.CAPACITY_LOSS and not self.service:
            raise ValueError("capacity loss requires service")
        if self.fault_type is OperationalFaultType.LINK_BROWNOUT and not (
            self.caller and self.callee
        ):
            raise ValueError("link brownout requires caller and callee")


@dataclass(frozen=True)
class FaultResult:
    metrics: dict[str, BaseLoadSeries]
    deploys: list[DeployRecord]
    logs: list[LogRecord]
    traces: list[TraceRecord]


def load_fault_catalog(
    manifest_path: Path = DEFAULT_MANIFEST_LOCK_PATH,
) -> dict[str, FaultCatalogEntry]:
    """Load canonical fault metadata and real hashes from the materialized repo."""
    with manifest_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return {
        fault_id: FaultCatalogEntry(
            fault_id=fault_id,
            files=tuple(spec["files"]),
            **{
                key: value
                for key, value in spec.items()
                if key
                in {
                    "sub_type",
                    "mechanism",
                    "commit",
                    "fix_commit",
                    "file",
                    "line",
                    "function",
                    "pattern",
                    "service",
                    "author",
                    "summary",
                }
            },
        )
        for fault_id, spec in raw["faults"].items()
    }


def fault_strength(
    ts: np.ndarray,
    onset_ts: float,
    end_ts: float,
    severity: float,
    config: ScenarioConfig = CONFIG.scenario,
) -> np.ndarray:
    """Return a duration-relative ramp, plateau and decay fault strength."""
    duration = end_ts - onset_ts
    ramp_duration = min(duration / 2.0, duration * config.fault_ramp_fraction)
    plateau_start = onset_ts + ramp_duration
    plateau_end = end_ts - ramp_duration
    strength = np.zeros(len(ts), dtype=np.float64)
    ramp = (ts >= onset_ts) & (ts < plateau_start)
    plateau = (ts >= plateau_start) & (ts <= plateau_end)
    decay = (ts > plateau_end) & (ts < end_ts)
    if ramp_duration:
        strength[ramp] = severity * (ts[ramp] - onset_ts) / ramp_duration
        strength[decay] = severity * (end_ts - ts[decay]) / ramp_duration
    strength[plateau] = severity
    return strength


def deploy_record(entry: FaultCatalogEntry, spec: FaultSpec) -> DeployRecord:
    return DeployRecord(
        ts=spec.deploy_ts,
        service=entry.service,
        commit=entry.commit,
        author=entry.author,
        files=list(entry.files),
        summary=entry.summary,
    )


def _topology_upstream(topology_path: Path) -> dict[str, list[str]]:
    with topology_path.open(encoding="utf-8") as handle:
        topology = yaml.safe_load(handle)
    upstream: dict[str, list[str]] = {}
    for edge in topology["edges"]:
        upstream.setdefault(edge["callee"], []).append(edge["caller"])
    return upstream


def _propagate_upstream(
    metrics: dict[str, BaseLoadSeries],
    origin: str,
    strength: np.ndarray,
    topology_path: Path,
    config: ScenarioConfig,
) -> None:
    frontier = [(origin, 1.0)]
    seen = {origin}
    upstream = _topology_upstream(topology_path)
    while frontier:
        service, weight = frontier.pop(0)
        for caller in upstream.get(service, []):
            if caller in seen:
                continue
            seen.add(caller)
            caller_metrics = metrics[caller]
            effect = strength * weight
            metrics[caller] = replace(
                caller_metrics,
                err_rate=np.clip(
                    caller_metrics.err_rate + config.upstream_error_gain * effect,
                    0.0,
                    1.0,
                ),
                p95_ms=caller_metrics.p95_ms * (1.0 + config.upstream_latency_gain * effect),
                p99_ms=caller_metrics.p99_ms * (1.0 + config.upstream_latency_gain * effect),
            )
            frontier.append((caller, weight * config.upstream_attenuation))


def _evidence_records(
    entry: FaultCatalogEntry,
    spec: FaultSpec,
    metrics: dict[str, BaseLoadSeries],
    config: ScenarioConfig,
) -> tuple[LogRecord, TraceRecord | None]:
    midpoint = spec.onset_ts + (spec.end_ts - spec.onset_ts) / 2.0
    series = metrics[entry.service]
    index = int(np.searchsorted(series.ts, midpoint, side="left"))
    index = min(index, len(series.ts) - 1)
    log = LogRecord(
        ts=midpoint,
        service=entry.service,
        level="error",
        template_id=entry.sub_type.upper(),
        msg=f"{entry.mechanism} detected after deploy {entry.commit[:12]}",
        count=max(1, round(config.fault_log_count_scale * spec.severity)),
    )
    trace: TraceRecord | None = None
    if entry.fault_id == "F1":
        notify = metrics["notify-svc"]
        trace = TraceRecord(
            ts=midpoint,
            caller="payment-svc",
            callee="notify-svc",
            rps=float(notify.rps[index]),
            err_rate=float(np.clip(notify.err_rate[index], 0.0, 1.0)),
            p99_ms=float(notify.p99_ms[index]),
        )
    return log, trace


def apply_code_faults(
    metrics: dict[str, BaseLoadSeries],
    faults: list[FaultSpec],
    *,
    manifest_path: Path = DEFAULT_MANIFEST_LOCK_PATH,
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
    capacities: dict[str, ServiceCapacity] | None = None,
    config: ScenarioConfig = CONFIG.scenario,
) -> FaultResult:
    """Apply F1–F6 local signatures and topology-derived cascades."""
    catalog = load_fault_catalog(manifest_path)
    capacities = capacities or load_service_capacities(topology_path)
    result = dict(metrics)
    deploys: list[DeployRecord] = []
    logs: list[LogRecord] = []
    traces: list[TraceRecord] = []

    for spec in faults:
        if spec.fault_id not in catalog:
            raise ValueError(f"unknown fault id: {spec.fault_id}")
        entry = catalog[spec.fault_id]
        series = result[entry.service]
        strength = fault_strength(series.ts, spec.onset_ts, spec.end_ts, spec.severity, config)
        updated = series

        if entry.fault_id == "F1":
            notify = result["notify-svc"]
            amplified_rps = notify.rps * (1.0 + config.retry_amplification_gain * strength)
            result["notify-svc"] = replace(
                notify,
                rps=amplified_rps,
                **derive_capacity_metrics(amplified_rps, capacities["notify-svc"], config),
            )
            updated = replace(
                series,
                err_rate=np.clip(
                    series.err_rate + config.retry_error_gain * strength,
                    0.0,
                    1.0,
                ),
                queue_depth=series.queue_depth + config.pool_queue_gain * strength,
            )
        elif entry.fault_id == "F2":
            updated = replace(
                series,
                conn_active=np.maximum(
                    series.conn_active,
                    capacities[entry.service].max_conns
                    * config.pool_connection_fraction
                    * strength,
                ),
                queue_depth=series.queue_depth + config.pool_queue_gain * strength,
                p95_ms=series.p95_ms * (1.0 + config.pool_latency_gain * strength),
                p99_ms=series.p99_ms * (1.0 + config.pool_latency_gain * strength),
            )
        elif entry.fault_id == "F3":
            elapsed = np.maximum(series.ts - spec.onset_ts, 0.0)
            burst = 0.5 + 0.5 * np.cos(2.0 * np.pi * elapsed / config.cache_burst_period_s)
            burst *= strength
            updated = replace(
                series,
                p95_ms=series.p95_ms * (1.0 + config.cache_latency_gain * burst),
                p99_ms=series.p99_ms * (1.0 + config.cache_latency_gain * burst),
                cpu_pct=np.clip(
                    series.cpu_pct + config.cache_cpu_gain_pct * burst,
                    0.0,
                    100.0,
                ),
            )
        elif entry.fault_id == "F4":
            progress = np.clip(
                (series.ts - spec.onset_ts) / (spec.end_ts - spec.onset_ts),
                0.0,
                1.0,
            )
            restart = (
                np.cos(
                    2.0
                    * np.pi
                    * progress
                    * (spec.end_ts - spec.onset_ts)
                    / config.leak_restart_period_s
                )
                > 0.96
            ).astype(float)
            updated = replace(
                series,
                mem_pct=np.clip(
                    series.mem_pct + config.leak_memory_gain_pct * progress * strength,
                    0.0,
                    100.0,
                ),
                err_rate=np.clip(series.err_rate + restart * strength, 0.0, 1.0),
            )
        elif entry.fault_id == "F5":
            updated = replace(
                series,
                p50_ms=series.p50_ms * (1.0 + config.nplus1_latency_gain * strength),
                p95_ms=series.p95_ms * (1.0 + config.nplus1_latency_gain * strength),
                p99_ms=series.p99_ms * (1.0 + config.nplus1_latency_gain * strength),
                cpu_pct=np.clip(
                    series.cpu_pct + config.nplus1_cpu_gain_pct * strength,
                    0.0,
                    100.0,
                ),
            )
        elif entry.fault_id == "F6":
            updated = replace(
                series,
                queue_depth=series.queue_depth + config.worker_queue_gain * strength,
                p95_ms=series.p95_ms * (1.0 + config.worker_latency_gain * strength),
                p99_ms=series.p99_ms * (1.0 + config.worker_latency_gain * strength),
            )

        result[entry.service] = updated
        _propagate_upstream(result, entry.service, strength, topology_path, config)
        deploys.append(deploy_record(entry, spec))
        log, trace = _evidence_records(entry, spec, result, config)
        logs.append(log)
        if trace:
            traces.append(trace)

    return FaultResult(metrics=result, deploys=deploys, logs=logs, traces=traces)


def apply_operational_faults(
    metrics: dict[str, BaseLoadSeries],
    faults: list[OperationalFaultSpec],
    *,
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
    capacities: dict[str, ServiceCapacity] | None = None,
    config: ScenarioConfig = CONFIG.scenario,
) -> FaultResult:
    """Apply non-code link brownouts and fleet-capacity loss."""
    capacities = capacities or load_service_capacities(topology_path)
    result = dict(metrics)
    logs: list[LogRecord] = []
    traces: list[TraceRecord] = []

    for spec in faults:
        reference = result[spec.service or spec.caller or ""]
        strength = fault_strength(reference.ts, spec.onset_ts, spec.end_ts, spec.severity, config)
        midpoint = spec.onset_ts + (spec.end_ts - spec.onset_ts) / 2.0
        index = min(int(np.searchsorted(reference.ts, midpoint)), len(reference.ts) - 1)
        if spec.fault_type is OperationalFaultType.CAPACITY_LOSS:
            service = spec.service or ""
            original = capacities[service]
            reduced = replace(
                original,
                capacity_rps=original.capacity_rps
                * (1.0 - config.capacity_loss_fraction * spec.severity),
            )
            local = result[service]
            derived = derive_capacity_metrics(local.rps, reduced, config)
            blended = {
                field: getattr(local, field) + (reduced_values - getattr(local, field)) * strength
                for field, reduced_values in derived.items()
            }
            result[service] = replace(local, **blended)
            _propagate_upstream(result, service, strength, topology_path, config)
            logs.append(
                LogRecord(
                    ts=midpoint,
                    service=service,
                    level="error",
                    template_id="CAPACITY_LOSS",
                    msg="available fleet capacity dropped without a deploy",
                    count=max(1, round(config.fault_log_count_scale * spec.severity)),
                )
            )
        else:
            caller = spec.caller or ""
            callee = spec.callee or ""
            caller_series = result[caller]
            result[caller] = replace(
                caller_series,
                err_rate=np.clip(
                    caller_series.err_rate + config.link_brownout_error_gain * strength,
                    0.0,
                    1.0,
                ),
                p99_ms=caller_series.p99_ms * (1.0 + config.link_brownout_latency_gain * strength),
            )
            traces.append(
                TraceRecord(
                    ts=midpoint,
                    caller=caller,
                    callee=callee,
                    rps=float(caller_series.rps[index]),
                    err_rate=float(
                        np.clip(
                            config.link_brownout_error_gain * spec.severity,
                            0.0,
                            1.0,
                        )
                    ),
                    p99_ms=float(result[caller].p99_ms[index]),
                )
            )

    return FaultResult(metrics=result, deploys=[], logs=logs, traces=traces)
