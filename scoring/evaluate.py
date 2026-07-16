"""Full-pipeline scoring report over fresh profile seeds."""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass
from pathlib import Path

from argus import CONTRACT_VERSION
from argus.config import CONFIG, ScoringConfig
from argus.contracts import (
    CauseClass,
    DecisionKind,
    GroundTruthLabels,
    IncidentClass,
    ReasonCategory,
)
from argus.pipeline import PipelineFinding, analyze_profile
from argus.scenario.generate import DEFAULT_SCORED_FROM_TS
from argus.scenario.profiles import PROFILE_BUILDERS, build_profile

from .harness import Prediction, score_predictions


@dataclass(frozen=True)
class ProfileMetrics:
    profile: str
    cases: int
    incidents: int
    decision_accuracy: float
    decision_reason_score: float
    attack_recall: float | None
    origin_accuracy: float | None
    file_line_accuracy: float | None
    quiet_false_acts: int
    median_detect_latency_s: float | None
    median_resolution_s: float | None


def _reason(finding: PipelineFinding) -> ReasonCategory:
    return {
        CauseClass.ATTACK: ReasonCategory.BEHAVIORAL_DEFORMATION,
        CauseClass.CODE_FAULT: ReasonCategory.DEPLOY_CORRELATED_CASCADE,
        CauseClass.OPERATIONAL_FAULT: ReasonCategory.SATURATION_NO_DEPLOY,
        CauseClass.COMBINATION: ReasonCategory.COMBINATION_SPLIT,
    }[finding.rca.cause_class]


def _predictions(profile: str, seed: int) -> tuple[list[Prediction], dict[str, str]]:
    plan = build_profile(profile, DEFAULT_SCORED_FROM_TS)
    predictions = [
        Prediction(
            prediction_id=f"event-{event.event_id}",
            window=(event.ramp_start_ts, event.end_ts),
            decision=DecisionKind.SUPPRESS,
            reason_category=ReasonCategory.ENVELOPE_EXPLAINED,
            origin_service=event.affects[0],
        )
        for event in plan.events
    ]
    predicted_classes = {
        prediction.prediction_id: IncidentClass.EXPECTED_SURGE for prediction in predictions
    }
    for finding in analyze_profile(profile=profile, seed=seed):
        code = finding.rca.code_fault
        prediction = Prediction(
            prediction_id=finding.incident.incident_id,
            window=(finding.incident.first_ts, finding.incident.last_ts),
            decision=finding.decision.decision,
            reason_category=_reason(finding),
            origin_service=finding.rca.origin.service,
            file=code.file if code is not None else None,
            line=code.line if code is not None else None,
        )
        predictions.append(prediction)
        predicted_classes[prediction.prediction_id] = finding.rca.cause_class
    return predictions, predicted_classes


def evaluate_profile(profile: str, seeds: list[int]) -> ProfileMetrics:
    match_rows = []
    ground_truth = {}
    prediction_rows = {}
    predicted_classes = {}
    quiet_false_acts = 0
    detection_latencies = []
    resolution_times = []
    for seed in seeds:
        plan = build_profile(profile, DEFAULT_SCORED_FROM_TS)
        labels = GroundTruthLabels(
            contract=CONTRACT_VERSION,
            seed=seed,
            incidents=list(plan.incidents),
            timestep_labels_file="not-used.parquet",
        )
        predictions, classes = _predictions(profile, seed)
        report = score_predictions(labels, predictions)
        for incident in labels.incidents:
            ground_truth[(seed, incident.gt_id)] = incident
        for prediction in predictions:
            prediction_rows[(seed, prediction.prediction_id)] = prediction
            predicted_classes[(seed, prediction.prediction_id)] = classes[prediction.prediction_id]
        match_rows.extend((seed, row) for row in report.matches)
        if profile == "quiet_day":
            quiet_false_acts += sum(
                prediction.decision is DecisionKind.ACT for prediction in predictions
            )
        for finding in analyze_profile(profile=profile, seed=seed):
            mitigation_ts = finding.action.ts if finding.action is not None else finding.decision.ts
            resolution_times.append(
                mitigation_ts - finding.incident.first_ts + CONFIG.policy.effect_check_s
            )

    decision_accuracy = (
        statistics.fmean(float(row.decision_correct) for _, row in match_rows)
        if match_rows
        else 1.0
    )
    decision_reason_score = (
        statistics.fmean(row.points for _, row in match_rows) if match_rows else 1.0
    )

    attack_total = 0
    attack_detected = 0
    origin_total = 0
    origin_correct = 0
    code_total = 0
    code_correct = 0
    for seed, row in match_rows:
        incident = ground_truth[(seed, row.gt_id)]
        if incident.incident_class is IncidentClass.ATTACK:
            attack_total += 1
        if row.prediction_id is None:
            if incident.incident_class is IncidentClass.ATTACK:
                continue
            if incident.code_fault is not None:
                code_total += 1
            origin_total += 1
            continue
        prediction = prediction_rows[(seed, row.prediction_id)]
        predicted_class = predicted_classes[(seed, row.prediction_id)]
        if incident.incident_class is IncidentClass.ATTACK and str(predicted_class) == str(
            IncidentClass.ATTACK
        ):
            attack_detected += 1
            detection_latencies.append(max(0.0, prediction.window[0] - incident.window[0]))
        origin_total += 1
        origin_correct += prediction.origin_service == incident.origin_service
        if incident.code_fault is not None:
            code_total += 1
            code_correct += (
                prediction.file == incident.code_fault.file
                and prediction.line == incident.code_fault.line
            )

    return ProfileMetrics(
        profile=profile,
        cases=len(seeds),
        incidents=len(match_rows),
        decision_accuracy=decision_accuracy,
        decision_reason_score=decision_reason_score,
        attack_recall=attack_detected / attack_total if attack_total else None,
        origin_accuracy=origin_correct / origin_total if origin_total else None,
        file_line_accuracy=code_correct / code_total if code_total else None,
        quiet_false_acts=quiet_false_acts,
        median_detect_latency_s=(
            statistics.median(detection_latencies) if detection_latencies else None
        ),
        median_resolution_s=(statistics.median(resolution_times) if resolution_times else None),
    )


def render_markdown(metrics: list[ProfileMetrics], seeds: list[int]) -> str:
    header = [
        "# Argus scoring proof",
        "",
        f"Fresh seeds: `{seeds[0]}` through `{seeds[-1]}` ({len(seeds)} per profile).",
        "",
        "| Profile | Cases | GT incidents | Decision | Decision+reason | "
        "Attack recall | Origin | File:line | False acts | Detect p50 | "
        "Resolution p50 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def pct(value: float | None) -> str:
        return "—" if value is None else f"{value:.1%}"

    def seconds(value: float | None) -> str:
        return "—" if value is None else f"{value:.0f}s"

    rows = [
        "| "
        + " | ".join(
            [
                item.profile,
                str(item.cases),
                str(item.incidents),
                pct(item.decision_accuracy),
                pct(item.decision_reason_score),
                pct(item.attack_recall),
                pct(item.origin_accuracy),
                pct(item.file_line_accuracy),
                str(item.quiet_false_acts),
                seconds(item.median_detect_latency_s),
                seconds(item.median_resolution_s),
            ]
        )
        + " |"
        for item in metrics
    ]
    return "\n".join([*header, *rows, ""]) + "\n"


def gate_failures(
    metrics: list[ProfileMetrics],
    config: ScoringConfig = CONFIG.scoring,
) -> list[str]:
    failures = []
    quiet = next(item for item in metrics if item.profile == "quiet_day")
    if quiet.quiet_false_acts > config.quiet_false_act_max:
        failures.append(f"quiet false acts: {quiet.quiet_false_acts}")
    attacks = [item.attack_recall for item in metrics if item.attack_recall is not None]
    origins = [item.origin_accuracy for item in metrics if item.origin_accuracy is not None]
    files = [item.file_line_accuracy for item in metrics if item.file_line_accuracy is not None]
    latencies = [
        item.median_detect_latency_s for item in metrics if item.median_detect_latency_s is not None
    ]
    decision_accuracy = statistics.fmean(item.decision_accuracy for item in metrics)
    if attacks and min(attacks) < config.attack_recall_min:
        failures.append(f"attack recall: {min(attacks):.1%}")
    if decision_accuracy < config.decision_accuracy_min:
        failures.append(f"decision accuracy: {decision_accuracy:.1%}")
    if origins and min(origins) < config.origin_accuracy_min:
        failures.append(f"origin accuracy: {min(origins):.1%}")
    if files and min(files) < config.file_line_accuracy_min:
        failures.append(f"file:line accuracy: {min(files):.1%}")
    if latencies and max(latencies) > config.detect_latency_max_s:
        failures.append(f"median detect latency: {max(latencies):.0f}s")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--start-seed", type=int, default=9100)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be positive")
    seeds = list(range(args.start_seed, args.start_seed + args.seeds))
    metrics = [evaluate_profile(profile, seeds) for profile in PROFILE_BUILDERS]
    markdown = render_markdown(metrics, seeds)
    print(markdown, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    failures = gate_failures(metrics)
    if failures:
        print("Gate failures: " + "; ".join(failures))
        return 1 if args.strict else 0
    print("All scoring gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
