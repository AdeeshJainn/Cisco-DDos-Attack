"""Ground-truth writers consumed only by scoring and tests, never runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from argus import CONTRACT_VERSION
from argus.contracts import GroundTruthIncident, GroundTruthLabels, ensure_ordered


@dataclass(frozen=True)
class StepLabelSpan:
    """Per-window fractions used to build the scoring-only timestep table."""

    gt_id: str
    start_ts: float
    end_ts: float
    explained_fraction: float = 0.0
    attack_fraction: float = 0.0
    fault_fraction: float = 0.0

    def __post_init__(self) -> None:
        ensure_ordered([("start_ts", self.start_ts), ("end_ts", self.end_ts)])
        if self.start_ts == self.end_ts:
            raise ValueError("step-label span must have positive duration")
        for name in ("explained_fraction", "attack_fraction", "fault_fraction"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


def build_step_label_table(
    timestamps: np.ndarray,
    spans: list[StepLabelSpan],
) -> pa.Table:
    """Build one deterministic row per scored timestamp."""
    ts = np.asarray(timestamps, dtype=np.float64)
    explained = np.zeros(len(ts), dtype=np.float64)
    attack = np.zeros(len(ts), dtype=np.float64)
    fault = np.zeros(len(ts), dtype=np.float64)
    active: list[list[str]] = [[] for _ in range(len(ts))]

    for span in spans:
        mask = (ts >= span.start_ts) & (ts <= span.end_ts)
        explained[mask] = np.maximum(explained[mask], span.explained_fraction)
        attack[mask] = np.maximum(attack[mask], span.attack_fraction)
        fault[mask] = np.maximum(fault[mask], span.fault_fraction)
        for index in np.flatnonzero(mask):
            active[int(index)].append(span.gt_id)

    return pa.table(
        {
            "ts": ts,
            "explained_fraction": explained,
            "attack_fraction": attack,
            "fault_fraction": fault,
            "active_gt_ids": [",".join(sorted(ids)) for ids in active],
        }
    )


def write_ground_truth(
    *,
    seed: int,
    incidents: list[GroundTruthIncident],
    timestamps: np.ndarray,
    spans: list[StepLabelSpan],
    labels_path: Path,
) -> GroundTruthLabels:
    """Write deterministic incident JSON plus a real Parquet timestep table."""
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    if labels_path.name.endswith(".labels.json"):
        step_name = labels_path.name.removesuffix(".labels.json") + ".steplabels.parquet"
    else:
        step_name = labels_path.stem + ".steplabels.parquet"
    step_path = labels_path.with_name(step_name)

    labels = GroundTruthLabels(
        contract=CONTRACT_VERSION,
        seed=seed,
        incidents=incidents,
        timestep_labels_file=step_path.name,
    )
    payload = json.dumps(
        labels.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    labels_path.write_text(payload + "\n", encoding="utf-8")

    table = build_step_label_table(timestamps, spans)
    pq.write_table(
        table,
        step_path,
        compression="zstd",
        version="2.6",
        write_statistics=True,
    )
    return labels
