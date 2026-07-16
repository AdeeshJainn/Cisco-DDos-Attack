"""MTTR tracking from detection to verified restoration, with baselines."""

from __future__ import annotations

from argus.config import CONFIG, PolicyConfig
from argus.contracts import MttrRecord


def mttr_record(
    *,
    incident_id: str,
    onset_ts: float,
    detected_ts: float,
    root_caused_ts: float,
    mitigated_ts: float,
    verified_ts: float,
    config: PolicyConfig = CONFIG.policy,
) -> MttrRecord:
    return MttrRecord(
        incident_id=incident_id,
        onset_ts=onset_ts,
        detected_ts=detected_ts,
        root_caused_ts=root_caused_ts,
        mitigated_ts=mitigated_ts,
        verified_ts=verified_ts,
        manual_baseline_s=config.manual_baseline_s,
        autonomous_s=verified_ts - onset_ts,
    )
