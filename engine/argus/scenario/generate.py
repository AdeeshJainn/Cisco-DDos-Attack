"""Scenario composition and deterministic compressed stream writer."""

from __future__ import annotations

import gzip
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from argus.config import CONFIG, ScenarioConfig
from argus.contracts import MetricName, ScenarioHeader
from argus.scenario.attacks import apply_attacks
from argus.scenario.base import (
    build_scenario_header,
    generate_base_load,
)
from argus.scenario.events import (
    apply_events,
    calendar_records,
    generate_organic_net_features,
)
from argus.scenario.faults import apply_code_faults, apply_operational_faults
from argus.scenario.labels import write_ground_truth
from argus.scenario.profiles import build_profile

DEFAULT_SCORED_FROM_TS = 1789430400.0
METRIC_FIELDS: tuple[tuple[MetricName, str], ...] = (
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


@dataclass(frozen=True)
class ScenarioArtifacts:
    scenario_path: Path
    labels_path: Path
    step_labels_path: Path
    header: ScenarioHeader


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def _write_jsonl_gzip(
    path: Path,
    header: ScenarioHeader,
    metrics,
    network,
    markers: list[Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    services = header.services
    reference = metrics[services[0]]
    marker_index = 0
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as stream,
    ):
        stream.write(_json_line(header.model_dump(mode="json")))
        for index, ts in enumerate(reference.ts):
            while marker_index < len(markers) and markers[marker_index].ts <= ts:
                marker = markers[marker_index]
                stream.write(_json_line(marker.model_dump(mode="json")))
                marker_index += 1
            for service in services:
                series = metrics[service]
                for name, field in METRIC_FIELDS:
                    stream.write(
                        _json_line(
                            {
                                "kind": "metric",
                                "ts": float(ts),
                                "service": service,
                                "name": name,
                                "value": float(getattr(series, field)[index]),
                            }
                        )
                    )
                net = network[service]
                stream.write(
                    _json_line(
                        {
                            "kind": "net",
                            "ts": float(ts),
                            "service": service,
                            "uniq_ip_entropy": float(net.uniq_ip_entropy[index]),
                            "syn_ack_ratio": float(net.syn_ack_ratio[index]),
                            "auth_fail_ratio": float(net.auth_fail_ratio[index]),
                            "ja3_novelty": float(net.ja3_novelty[index]),
                            "geo_top1_share": float(net.geo_top1_share[index]),
                        }
                    )
                )
        for marker in markers[marker_index:]:
            stream.write(_json_line(marker.model_dump(mode="json")))


def generate(
    *,
    seed: int,
    profile: str,
    output_dir: Path,
    scored_from_ts: float = DEFAULT_SCORED_FROM_TS,
    config: ScenarioConfig = CONFIG.scenario,
) -> ScenarioArtifacts:
    """Generate one scenario stream and its scoring-only ground truth."""
    rng = np.random.Generator(np.random.PCG64(seed))
    header = build_scenario_header(
        seed=seed,
        profile=profile,
        scored_from_ts=scored_from_ts,
        config=config,
    )
    plan = build_profile(profile, scored_from_ts)
    metrics = generate_base_load(rng, header, config=config)
    metrics = apply_events(metrics, list(plan.events), config=config)
    network = {
        service: generate_organic_net_features(rng, service, series.ts, config)
        for service, series in metrics.items()
    }
    attacked = apply_attacks(
        metrics,
        network,
        list(plan.attacks),
        config=config,
    )
    code_faulted = apply_code_faults(
        attacked.metrics,
        list(plan.code_faults),
        config=config,
    )
    operational = apply_operational_faults(
        code_faulted.metrics,
        list(plan.operational_faults),
        config=config,
    )

    name = f"{profile}-seed-{seed}"
    scenario_path = output_dir / f"{name}.jsonl.gz"
    labels_path = output_dir / f"{name}.labels.json"
    markers = [
        *(record for event in plan.events for record in calendar_records(event)),
        *code_faulted.deploys,
        *code_faulted.logs,
        *code_faulted.traces,
        *operational.logs,
        *operational.traces,
    ]
    markers.sort(key=lambda record: (record.ts, record.kind))
    _write_jsonl_gzip(
        scenario_path,
        header,
        operational.metrics,
        attacked.network,
        markers,
    )
    scored_timestamps = operational.metrics[header.services[0]].ts
    scored_timestamps = scored_timestamps[scored_timestamps >= header.scored_from_ts]
    labels = write_ground_truth(
        seed=seed,
        incidents=list(plan.incidents),
        timestamps=scored_timestamps,
        spans=list(plan.step_spans),
        labels_path=labels_path,
    )
    return ScenarioArtifacts(
        scenario_path=scenario_path,
        labels_path=labels_path,
        step_labels_path=labels_path.with_name(labels.timestep_labels_file),
        header=header,
    )
