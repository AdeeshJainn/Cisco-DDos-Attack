"""Decision-and-reason scoring harness over ground-truth incident windows."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from argus.config import CONFIG, ScoringConfig
from argus.contracts import (
    DecisionKind,
    GroundTruthIncident,
    GroundTruthLabels,
    ReasonCategory,
)


@dataclass(frozen=True)
class Prediction:
    prediction_id: str
    window: tuple[float, float]
    decision: DecisionKind
    reason_category: ReasonCategory
    origin_service: str | None = None
    file: str | None = None
    line: int | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> Prediction:
        return cls(
            prediction_id=raw["prediction_id"],
            window=tuple(raw["window"]),
            decision=DecisionKind(raw["decision"]),
            reason_category=ReasonCategory(raw["reason_category"]),
            origin_service=raw.get("origin_service"),
            file=raw.get("file"),
            line=raw.get("line"),
        )


@dataclass(frozen=True)
class MatchScore:
    gt_id: str
    prediction_id: str | None
    iou: float
    decision_correct: bool
    reason_correct: bool
    points: float
    origin_correct: bool | None
    file_line_correct: bool | None


@dataclass(frozen=True)
class ScoreReport:
    matches: tuple[MatchScore, ...]
    false_positives: int
    decision_accuracy: float
    decision_reason_score: float
    origin_accuracy: float | None
    file_line_accuracy: float | None


def window_iou(left: tuple[float, float], right: tuple[float, float]) -> float:
    intersection = max(0.0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union else 0.0


def score_predictions(
    labels: GroundTruthLabels,
    predictions: list[Prediction],
    config: ScoringConfig = CONFIG.scoring,
) -> ScoreReport:
    unmatched = set(range(len(predictions)))
    scores: list[MatchScore] = []
    for incident in labels.incidents:
        best_index, best_iou = _best_match(incident, predictions, unmatched)
        if best_index is None or best_iou < config.incident_iou_threshold:
            scores.append(
                MatchScore(
                    gt_id=incident.gt_id,
                    prediction_id=None,
                    iou=best_iou,
                    decision_correct=False,
                    reason_correct=False,
                    points=0.0,
                    origin_correct=None,
                    file_line_correct=None,
                )
            )
            continue
        unmatched.remove(best_index)
        prediction = predictions[best_index]
        decision_correct = prediction.decision is incident.correct_decision
        reason_correct = prediction.reason_category is incident.reason_category
        points = (
            1.0
            if decision_correct and reason_correct
            else config.wrong_reason_partial_credit
            if decision_correct
            else 0.0
        )
        origin_correct = (
            prediction.origin_service == incident.origin_service
            if prediction.origin_service is not None
            else None
        )
        file_line_correct = _file_line_correct(incident, prediction)
        scores.append(
            MatchScore(
                gt_id=incident.gt_id,
                prediction_id=prediction.prediction_id,
                iou=best_iou,
                decision_correct=decision_correct,
                reason_correct=reason_correct,
                points=points,
                origin_correct=origin_correct,
                file_line_correct=file_line_correct,
            )
        )

    denominator = len(scores) or 1
    origin_values = [score.origin_correct for score in scores if score.origin_correct is not None]
    file_values = [
        score.file_line_correct for score in scores if score.file_line_correct is not None
    ]
    return ScoreReport(
        matches=tuple(scores),
        false_positives=len(unmatched),
        decision_accuracy=sum(score.decision_correct for score in scores) / denominator,
        decision_reason_score=sum(score.points for score in scores) / denominator,
        origin_accuracy=_optional_average(origin_values),
        file_line_accuracy=_optional_average(file_values),
    )


def _best_match(
    incident: GroundTruthIncident,
    predictions: list[Prediction],
    candidates: set[int],
) -> tuple[int | None, float]:
    ranked = sorted(
        ((index, window_iou(incident.window, predictions[index].window)) for index in candidates),
        key=lambda item: (-item[1], predictions[item[0]].prediction_id),
    )
    return ranked[0] if ranked else (None, 0.0)


def _file_line_correct(
    incident: GroundTruthIncident,
    prediction: Prediction,
) -> bool | None:
    if incident.code_fault is None or prediction.file is None or prediction.line is None:
        return None
    return (
        prediction.file == incident.code_fault.file and prediction.line == incident.code_fault.line
    )


def _optional_average(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    labels = GroundTruthLabels.model_validate_json(args.labels.read_bytes())
    predictions = [
        Prediction.from_dict(item)
        for item in json.loads(args.predictions.read_text(encoding="utf-8"))
    ]
    report = score_predictions(labels, predictions)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
