"""Robust seasonal expected band plus visible event context."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from argus.config import CONFIG, DetectionConfig
from argus.scenario.base import SECONDS_PER_DAY
from argus.scenario.events import EventSpec, event_envelope


@dataclass(frozen=True)
class ExpectedBand:
    base: np.ndarray
    event: np.ndarray
    low: np.ndarray
    high: np.ndarray
    half_width: np.ndarray


class SeasonalBaseline:
    """Median/MAD by time-of-day bucket learned only from prior history."""

    def __init__(
        self,
        bucket_median: dict[int, float],
        bucket_mad: dict[int, float],
        global_median: float,
        global_mad: float,
        config: DetectionConfig = CONFIG.detection,
    ) -> None:
        self.bucket_median = bucket_median
        self.bucket_mad = bucket_mad
        self.global_median = global_median
        self.global_mad = global_mad
        self.config = config

    @classmethod
    def fit(
        cls,
        ts: np.ndarray,
        values: np.ndarray,
        config: DetectionConfig = CONFIG.detection,
    ) -> SeasonalBaseline:
        timestamps = np.asarray(ts, dtype=np.float64)
        observed = np.asarray(values, dtype=np.float64)
        if not len(observed) or len(timestamps) != len(observed):
            raise ValueError("baseline history must be non-empty and aligned")
        buckets = np.mod(timestamps.astype(np.int64), SECONDS_PER_DAY) // config.seasonal_bucket_s
        medians: dict[int, float] = {}
        mads: dict[int, float] = {}
        for bucket in np.unique(buckets):
            sample = observed[buckets == bucket]
            median = float(np.median(sample))
            medians[int(bucket)] = median
            mads[int(bucket)] = float(np.median(np.abs(sample - median)))
        global_median = float(np.median(observed))
        global_mad = float(np.median(np.abs(observed - global_median)))
        return cls(medians, mads, global_median, global_mad, config)

    def predict(self, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        timestamps = np.asarray(ts, dtype=np.float64)
        buckets = (
            np.mod(timestamps.astype(np.int64), SECONDS_PER_DAY) // self.config.seasonal_bucket_s
        )
        base = np.asarray(
            [self.bucket_median.get(int(bucket), self.global_median) for bucket in buckets]
        )
        mad = np.asarray([self.bucket_mad.get(int(bucket), self.global_mad) for bucket in buckets])
        for index in range(1, len(base)):
            alpha = self.config.expected_ewma_alpha
            base[index] = alpha * base[index] + (1.0 - alpha) * base[index - 1]
        return base, mad


def expected_band(
    baseline: SeasonalBaseline,
    ts: np.ndarray,
    *,
    service: str,
    events: list[EventSpec],
    config: DetectionConfig = CONFIG.detection,
) -> ExpectedBand:
    base, mad = baseline.predict(ts)
    multiplier = np.ones(len(base), dtype=np.float64)
    for event in events:
        if service in event.affects:
            multiplier *= event_envelope(np.asarray(ts), event)
    event = base * (multiplier - 1.0)
    expected = base + event
    robust_width = config.band_k * config.mad_scale * mad
    half_width = np.maximum(
        robust_width,
        np.maximum(np.abs(expected), 1.0) * config.minimum_band_fraction,
    )
    return ExpectedBand(
        base=base,
        event=event,
        low=expected - half_width,
        high=expected + half_width,
        half_width=half_width,
    )
