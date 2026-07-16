"""Headless observable-to-decision pipeline for arbitrary profile seeds."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from argus.config import CONFIG, DetectionConfig
from argus.contracts import (
    Action,
    Decision,
    DeployRecord,
    Incident,
    IncidentStatus,
    RcaResult,
    Symptom,
    SymptomKind,
    Verdict,
)
from argus.detection.expected import SeasonalBaseline, expected_band
from argus.policy.decide import decide
from argus.policy.ladder import first_action
from argus.rca.collapse import analyze
from argus.scenario.attacks import apply_attacks
from argus.scenario.base import build_scenario_header, generate_base_load
from argus.scenario.events import apply_events, generate_organic_net_features
from argus.scenario.faults import apply_code_faults, apply_operational_faults
from argus.scenario.generate import DEFAULT_SCORED_FROM_TS
from argus.scenario.profiles import build_profile
from argus.verdict.rules import classify

NET_SIGNALS = (
    "uniq_ip_entropy",
    "syn_ack_ratio",
    "auth_fail_ratio",
    "ja3_novelty",
    "geo_top1_share",
)
INTERNAL_SIGNALS = (
    "err_rate",
    "p95_ms",
    "p99_ms",
    "cpu_pct",
    "mem_pct",
    "conn_active",
    "queue_depth",
)


@dataclass(frozen=True)
class PipelineFinding:
    incident: Incident
    verdict: Verdict
    rca: RcaResult
    decision: Decision
    action: Action | None

    def model_dump(self) -> dict:
        return {
            "incident": self.incident.model_dump(mode="json"),
            "verdict": self.verdict.model_dump(mode="json"),
            "rca": self.rca.model_dump(mode="json"),
            "decision": self.decision.model_dump(mode="json"),
            "action": (self.action.model_dump(mode="json") if self.action is not None else None),
        }


def _first_sustained(mask: np.ndarray, sustain_samples: int) -> tuple[int, int] | None:
    padded = np.concatenate(([False], mask, [False]))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    for start, end in zip(starts, ends, strict=True):
        if end - start >= sustain_samples:
            return int(start), int(end - 1)
    return None


def _robust_scores(
    history: np.ndarray,
    values: np.ndarray,
    config: DetectionConfig,
) -> np.ndarray:
    median = float(np.median(history))
    mad = float(np.median(np.abs(history - median)))
    denominator = max(
        config.mad_scale * mad,
        config.ratio_epsilon * max(abs(median), 1.0),
    )
    return np.abs(values - median) / denominator


def _attack_findings(
    *,
    metrics,
    network,
    events,
    scored_from_ts: float,
    config: DetectionConfig,
) -> list[Incident]:
    incidents = []
    for service, net in network.items():
        warmup = net.ts < scored_from_ts
        scored = ~warmup
        scored_ts = net.ts[scored]
        symptoms = []
        window_start = None
        window_end = None
        for signal in NET_SIGNALS:
            values = getattr(net, signal)
            z = _robust_scores(values[warmup], values[scored], config)
            run = _first_sustained(
                z >= config.ratio_enter_z,
                max(1, round(config.ratio_sustain_s)),
            )
            if run is None:
                continue
            start, end = run
            onset = float(scored_ts[start])
            symptoms.append(
                Symptom(
                    service=service,
                    signal=signal,
                    kind=SymptomKind.RATIO_DEFORM,
                    onset_ts=onset,
                    score=float(
                        np.clip(np.max(z[start : end + 1]) / config.ratio_score_cap_z, 0, 1)
                    ),
                )
            )
            window_start = onset if window_start is None else min(window_start, onset)
            window_end = (
                float(scored_ts[end])
                if window_end is None
                else max(
                    window_end,
                    float(scored_ts[end]),
                )
            )
        if not symptoms or window_start is None or window_end is None:
            continue

        series = metrics[service]
        warm = series.ts < scored_from_ts
        visible = ~warm
        baseline = SeasonalBaseline.fit(series.ts[warm], series.rps[warm], config)
        band = expected_band(
            baseline,
            series.ts[visible],
            service=service,
            events=list(events),
            config=config,
        )
        residual = series.rps[visible] - band.base - band.event
        normalized = np.abs(residual) / band.half_width
        score = np.clip(
            (normalized - 1.0) / (config.residual_score_cap - 1.0),
            0.0,
            1.0,
        )
        onset_index = int(np.searchsorted(series.ts[visible], window_start))
        symptoms.append(
            Symptom(
                service=service,
                signal="rps",
                kind=SymptomKind.RESIDUAL_EXCEED,
                onset_ts=window_start,
                score=float(score[min(onset_index, len(score) - 1)]),
            )
        )
        incidents.append(
            Incident(
                incident_id=f"inc-attack-{service}",
                status=IncidentStatus.OPEN,
                first_ts=window_start,
                last_ts=window_end,
                symptoms=symptoms,
            )
        )
    return incidents


def _metric_window(
    series,
    *,
    scored_from_ts: float,
    config: DetectionConfig,
) -> tuple[float, float, str, float] | None:
    warmup = series.ts < scored_from_ts
    scored = ~warmup
    scored_ts = series.ts[scored]
    candidates = []
    for signal in INTERNAL_SIGNALS:
        values = getattr(series, signal)
        baseline = SeasonalBaseline.fit(series.ts[warmup], values[warmup], config)
        band = expected_band(
            baseline,
            scored_ts,
            service=series.service,
            events=[],
            config=config,
        )
        normalized = np.abs(values[scored] - band.base) / band.half_width
        scores = np.clip(
            (normalized - 1.0) / (config.residual_score_cap - 1.0),
            0.0,
            1.0,
        )
        run = _first_sustained(
            scores >= config.symptom_enter_score,
            max(1, round(config.symptom_sustain_s)),
        )
        if run is None:
            continue
        start, end = run
        candidates.append(
            (
                float(scored_ts[start]),
                float(scored_ts[end]),
                signal,
                float(np.max(scores[start : end + 1])),
            )
        )
    return min(candidates, key=lambda item: (item[0], -item[3]), default=None)


def _fault_findings(
    metrics,
    logs,
    traces,
    deploys: list[DeployRecord],
    *,
    scored_from_ts: float,
) -> list[Incident]:
    incidents = []
    for index, log in enumerate(logs, start=1):
        deploy = max(
            (item for item in deploys if item.service == log.service and item.ts <= log.ts),
            key=lambda item: item.ts,
            default=None,
        )
        metric_window = _metric_window(
            metrics[log.service],
            scored_from_ts=scored_from_ts,
            config=CONFIG.detection,
        )
        incident_start = metric_window[0] if metric_window else log.ts
        incident_end = (
            metric_window[1] if metric_window else (log.ts + CONFIG.detection.symptom_sustain_s)
        )
        symptoms = [
            Symptom(
                service=log.service,
                signal=log.template_id,
                kind=SymptomKind.LOG_BURST,
                onset_ts=log.ts,
                score=min(1.0, log.count / CONFIG.scenario.fault_log_count_scale),
            )
        ]
        if metric_window is not None:
            symptoms.append(
                Symptom(
                    service=log.service,
                    signal=metric_window[2],
                    kind=SymptomKind.SATURATION,
                    onset_ts=metric_window[0],
                    score=metric_window[3],
                )
            )
        if deploy is not None:
            symptoms.append(
                Symptom(
                    service=deploy.service,
                    signal=deploy.commit,
                    kind=SymptomKind.DEPLOY_MARKER,
                    onset_ts=deploy.ts,
                    score=1.0,
                )
            )
        for trace in traces:
            if abs(trace.ts - log.ts) <= CONFIG.rca.incident_gap_s and (
                trace.caller == log.service or trace.callee == log.service
            ):
                symptoms.append(
                    Symptom(
                        service=trace.caller,
                        signal=f"{trace.caller}->{trace.callee}",
                        kind=SymptomKind.EDGE_DEGRADED,
                        onset_ts=trace.ts,
                        score=min(1.0, max(trace.err_rate, trace.p99_ms / 5000.0)),
                    )
                )
        incidents.append(
            Incident(
                incident_id=f"inc-fault-{index:02d}",
                status=IncidentStatus.OPEN,
                first_ts=incident_start,
                last_ts=incident_end,
                symptoms=symptoms,
            )
        )
    return incidents


@lru_cache(maxsize=16)
def analyze_profile(
    *,
    profile: str,
    seed: int,
    scored_from_ts: float = DEFAULT_SCORED_FROM_TS,
) -> list[PipelineFinding]:
    """Generate observables, then classify them without consulting labels."""
    rng = np.random.Generator(np.random.PCG64(seed))
    header = build_scenario_header(
        seed=seed,
        profile=profile,
        scored_from_ts=scored_from_ts,
    )
    plan = build_profile(profile, scored_from_ts)
    metrics = apply_events(generate_base_load(rng, header), list(plan.events))
    network = {
        service: generate_organic_net_features(rng, service, series.ts)
        for service, series in metrics.items()
    }
    attacked = apply_attacks(metrics, network, list(plan.attacks))
    code = apply_code_faults(attacked.metrics, list(plan.code_faults))
    operational = apply_operational_faults(
        code.metrics,
        list(plan.operational_faults),
    )
    deploys = code.deploys
    incidents = [
        *_attack_findings(
            metrics=operational.metrics,
            network=attacked.network,
            events=plan.events,
            scored_from_ts=scored_from_ts,
            config=CONFIG.detection,
        ),
        *_fault_findings(
            operational.metrics,
            [*code.logs, *operational.logs],
            [*code.traces, *operational.traces],
            deploys,
            scored_from_ts=scored_from_ts,
        ),
    ]
    findings = []
    for incident in incidents:
        verdict = classify(incident)
        rca = analyze(incident, verdict, deploys)
        decision = decide(verdict, ts=incident.last_ts)
        action = first_action(decision, verdict, ts=incident.last_ts + 1.0)
        findings.append(
            PipelineFinding(
                incident=incident,
                verdict=verdict,
                rca=rca,
                decision=decision,
                action=action,
            )
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the observable-to-decision pipeline on a seeded profile."
    )
    parser.add_argument("--profile", default="combo_night")
    parser.add_argument("--seed", type=int, default=424242)
    args = parser.parse_args()
    findings = analyze_profile(profile=args.profile, seed=args.seed)
    print(json.dumps([item.model_dump() for item in findings], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
