"""Behavioral-ratio monitors with rolling robust z-scores."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from argus.config import CONFIG, DetectionConfig


@dataclass(frozen=True)
class RatioObservation:
    ts: float
    signal: str
    value: float
    robust_z: float
    score: float
    deformed: bool
    onset_ts: float | None


class RatioMonitor:
    """Online robust monitor whose baseline excludes active incidents."""

    def __init__(
        self,
        signal: str,
        config: DetectionConfig = CONFIG.detection,
    ) -> None:
        self.signal = signal
        self.config = config
        self._history: deque[tuple[float, float]] = deque()
        self._candidate_since: float | None = None
        self._onset_ts: float | None = None
        self._deformed = False

    def update(
        self,
        *,
        ts: float,
        value: float,
        incident_open: bool = False,
    ) -> RatioObservation:
        while self._history and self._history[0][0] < ts - self.config.ratio_window_s:
            self._history.popleft()

        robust_z = self._robust_z(value)
        magnitude = abs(robust_z)
        if self._deformed:
            if magnitude < self.config.ratio_release_z:
                self._deformed = False
                self._candidate_since = None
                self._onset_ts = None
        elif magnitude >= self.config.ratio_enter_z:
            if self._candidate_since is None:
                self._candidate_since = ts
            if ts - self._candidate_since >= self.config.ratio_sustain_s:
                self._deformed = True
                self._onset_ts = self._candidate_since
        else:
            self._candidate_since = None

        if not incident_open:
            self._history.append((ts, value))
        return RatioObservation(
            ts=ts,
            signal=self.signal,
            value=value,
            robust_z=robust_z,
            score=float(np.clip(magnitude / self.config.ratio_score_cap_z, 0.0, 1.0)),
            deformed=self._deformed,
            onset_ts=self._onset_ts,
        )

    def _robust_z(self, value: float) -> float:
        if len(self._history) < self.config.ratio_min_samples:
            return 0.0
        history = np.fromiter((item[1] for item in self._history), dtype=np.float64)
        median = float(np.median(history))
        mad = float(np.median(np.abs(history - median)))
        denominator = max(
            self.config.mad_scale * mad,
            self.config.ratio_epsilon * max(abs(median), 1.0),
        )
        return (value - median) / denominator
