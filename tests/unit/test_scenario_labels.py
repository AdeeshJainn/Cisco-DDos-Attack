"""P3.5 scoring-only incident and timestep label writers."""

import json

import numpy as np
import pyarrow.parquet as pq
import pytest
from argus.contracts import (
    CodeFaultLabel,
    DecisionKind,
    GroundTruthIncident,
    IncidentClass,
    ReasonCategory,
)
from argus.scenario.labels import StepLabelSpan, build_step_label_table, write_ground_truth


def _incidents() -> list[GroundTruthIncident]:
    return [
        GroundTruthIncident(
            gt_id="gt-attack",
            incident_class=IncidentClass.ATTACK,
            sub_type="app_layer_flood",
            window=(30.0, 60.0),
            origin_service="edge-gw",
            inside_event="match",
            correct_decision=DecisionKind.ACT,
            reason_category=ReasonCategory.BEHAVIORAL_DEFORMATION,
            code_fault=None,
        ),
        GroundTruthIncident(
            gt_id="gt-code",
            incident_class=IncidentClass.CODE_FAULT,
            sub_type="retry_storm",
            window=(50.0, 80.0),
            origin_service="payment-svc",
            inside_event=None,
            correct_decision=DecisionKind.ACT,
            reason_category=ReasonCategory.DEPLOY_CORRELATED_CASCADE,
            code_fault=CodeFaultLabel(
                commit="45d03f4c223f73f50eefac8d010b9f533cc4c69c",
                file="payment_svc/retry.py",
                line=18,
                mechanism="unbounded_retry_no_backoff",
            ),
        ),
    ]


def _spans() -> list[StepLabelSpan]:
    return [
        StepLabelSpan(
            gt_id="gt-event",
            start_ts=20.0,
            end_ts=70.0,
            explained_fraction=0.8,
        ),
        StepLabelSpan(
            gt_id="gt-attack",
            start_ts=30.0,
            end_ts=60.0,
            attack_fraction=0.5,
        ),
        StepLabelSpan(
            gt_id="gt-code",
            start_ts=50.0,
            end_ts=80.0,
            fault_fraction=0.7,
        ),
    ]


def test_step_label_table_tracks_overlaps_and_active_ids():
    table = build_step_label_table(np.arange(0.0, 100.0, 10.0), _spans()).to_pydict()
    overlap = table["ts"].index(50.0)

    assert table["explained_fraction"][overlap] == 0.8
    assert table["attack_fraction"][overlap] == 0.5
    assert table["fault_fraction"][overlap] == 0.7
    assert table["active_gt_ids"][overlap] == "gt-attack,gt-code,gt-event"


def test_writer_emits_contract_json_and_real_parquet(tmp_path):
    labels_path = tmp_path / "combo.labels.json"
    labels = write_ground_truth(
        seed=424242,
        incidents=_incidents(),
        timestamps=np.arange(0.0, 100.0, 10.0),
        spans=_spans(),
        labels_path=labels_path,
    )

    raw = json.loads(labels_path.read_text())
    assert raw == labels.model_dump(mode="json")
    step_path = tmp_path / labels.timestep_labels_file
    assert step_path.read_bytes()[:4] == b"PAR1"
    table = pq.read_table(step_path)
    assert table.column_names == [
        "ts",
        "explained_fraction",
        "attack_fraction",
        "fault_fraction",
        "active_gt_ids",
    ]
    assert table.num_rows == 10


def test_writer_is_byte_deterministic(tmp_path):
    kwargs = {
        "seed": 7,
        "incidents": _incidents(),
        "timestamps": np.arange(0.0, 100.0, 10.0),
        "spans": _spans(),
    }
    first = tmp_path / "first" / "scenario.labels.json"
    second = tmp_path / "second" / "scenario.labels.json"
    write_ground_truth(labels_path=first, **kwargs)
    write_ground_truth(labels_path=second, **kwargs)

    assert first.read_bytes() == second.read_bytes()
    assert (
        first.with_name("scenario.steplabels.parquet").read_bytes()
        == second.with_name("scenario.steplabels.parquet").read_bytes()
    )


def test_step_span_rejects_invalid_fraction():
    with pytest.raises(ValueError, match="attack_fraction"):
        StepLabelSpan(
            gt_id="bad",
            start_ts=0.0,
            end_ts=1.0,
            attack_fraction=1.1,
        )
