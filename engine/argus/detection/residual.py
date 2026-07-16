"""Surge decomposition into base, event and unexplained residual."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

import numpy as np

from argus.config import CONFIG, DetectionConfig
from argus.contracts import DecompFrame, MetricName
from argus.scenario.events import EventSpec

from .expected import SeasonalBaseline, expected_band


def decompose(
    *,
    ts: np.ndarray,
    observed: np.ndarray,
    service: str,
    signal: MetricName,
    baseline: SeasonalBaseline,
    events: list[EventSpec],
    config: DetectionConfig = CONFIG.detection,
) -> Iterator[DecompFrame]:
    timestamps = np.asarray(ts, dtype=np.float64)
    values = np.asarray(observed, dtype=np.float64)
    if len(timestamps) != len(values):
        raise ValueError("timestamps and observed values must align")
    band = expected_band(
        baseline,
        timestamps,
        service=service,
        events=events if signal is MetricName.RPS else [],
        config=config,
    )
    expected = band.base + band.event
    residual = values - expected
    normalized = np.abs(residual) / band.half_width
    scores = np.clip(
        (normalized - 1.0) / (config.residual_score_cap - 1.0),
        0.0,
        1.0,
    )
    for index, timestamp in enumerate(timestamps):
        yield DecompFrame(
            ts=float(timestamp),
            service=service,
            signal=signal,
            observed=float(values[index]),
            explained_base=float(band.base[index]),
            explained_event=float(band.event[index]),
            residual=float(residual[index]),
            band=(float(band.low[index]), float(band.high[index])),
            residual_score=float(scores[index]),
        )


class DecompStore:
    """In-memory full-resolution frames for dashboard zoom queries."""

    def __init__(self) -> None:
        self._frames: dict[tuple[str, MetricName], list[DecompFrame]] = defaultdict(list)

    def add(self, frames: Iterator[DecompFrame]) -> None:
        for frame in frames:
            self._frames[(frame.service, frame.signal)].append(frame)

    def query(
        self,
        *,
        service: str,
        signal: MetricName,
        from_ts: float,
        to_ts: float,
        max_points: int,
    ) -> list[DecompFrame]:
        selected = [
            frame
            for frame in self._frames.get((service, signal), ())
            if from_ts <= frame.ts <= to_ts
        ]
        if len(selected) <= max_points:
            return selected
        indices = np.linspace(0, len(selected) - 1, max_points, dtype=int)
        return [selected[int(index)] for index in indices]
