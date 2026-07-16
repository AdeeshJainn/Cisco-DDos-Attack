"""P4.5 incident matching and decision+reason rubric tests."""

import json

from argus.contracts import GroundTruthLabels

from scoring.harness import Prediction, score_predictions, window_iou


def _labels() -> GroundTruthLabels:
    return GroundTruthLabels.model_validate(
        {
            "contract": "v1.0",
            "seed": 1,
            "incidents": [
                {
                    "gt_id": "gt-1",
                    "class": "attack",
                    "sub_type": "app_layer_flood",
                    "window": [100, 200],
                    "origin_service": "edge-gw",
                    "inside_event": "match",
                    "correct_decision": "act",
                    "reason_category": "behavioral_deformation",
                    "code_fault": None,
                },
                {
                    "gt_id": "gt-2",
                    "class": "code_fault",
                    "sub_type": "retry_storm",
                    "window": [300, 400],
                    "origin_service": "payment-svc",
                    "inside_event": None,
                    "correct_decision": "act",
                    "reason_category": "deploy_correlated_cascade",
                    "code_fault": {
                        "commit": "abc",
                        "file": "payment_svc/retry.py",
                        "line": 18,
                        "mechanism": "unbounded_retry_no_backoff",
                    },
                },
            ],
            "timestep_labels_file": "steps.parquet",
        }
    )


def test_window_iou():
    assert window_iou((0, 10), (5, 15)) == 1 / 3
    assert window_iou((0, 1), (2, 3)) == 0.0


def test_full_and_partial_reason_credit_with_rca_stubs():
    predictions = [
        Prediction.from_dict(
            {
                "prediction_id": "p1",
                "window": [110, 190],
                "decision": "act",
                "reason_category": "behavioral_deformation",
                "origin_service": "edge-gw",
            }
        ),
        Prediction.from_dict(
            {
                "prediction_id": "p2",
                "window": [310, 390],
                "decision": "act",
                "reason_category": "saturation_no_deploy",
                "origin_service": "payment-svc",
                "file": "payment_svc/retry.py",
                "line": 18,
            }
        ),
    ]
    report = score_predictions(_labels(), predictions)

    assert report.decision_accuracy == 1.0
    assert report.decision_reason_score == 0.75
    assert report.origin_accuracy == 1.0
    assert report.file_line_accuracy == 1.0


def test_miss_and_false_positive_are_counted():
    predictions = [
        Prediction.from_dict(
            {
                "prediction_id": "unrelated",
                "window": [500, 600],
                "decision": "alert",
                "reason_category": "saturation_no_deploy",
            }
        )
    ]
    report = score_predictions(_labels(), predictions)

    assert report.decision_accuracy == 0.0
    assert report.false_positives == 1
    assert all(match.prediction_id is None for match in report.matches)


def test_prediction_json_shape_is_plain_serializable():
    prediction = Prediction.from_dict(
        {
            "prediction_id": "p",
            "window": [1, 2],
            "decision": "suppress",
            "reason_category": "envelope_explained",
        }
    )
    assert json.loads(json.dumps(prediction.window)) == [1, 2]
