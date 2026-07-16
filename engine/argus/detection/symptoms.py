"""Symptom gating with hysteresis over detector outputs."""

from __future__ import annotations

from dataclasses import dataclass

from argus.config import CONFIG, DetectionConfig
from argus.contracts import (
    DecompFrame,
    DeployRecord,
    Symptom,
    SymptomKind,
    TraceRecord,
)

from .ratios import RatioObservation


@dataclass(frozen=True)
class SymptomTransition:
    symptom: Symptom
    opened: bool


@dataclass
class _GateState:
    candidate_since: float | None = None
    onset_ts: float | None = None
    active: bool = False


class SymptomDetector:
    """One hysteresis state machine per service/signal/symptom kind."""

    def __init__(self, config: DetectionConfig = CONFIG.detection) -> None:
        self.config = config
        self._states: dict[tuple[str, str, SymptomKind], _GateState] = {}

    def update(
        self,
        *,
        service: str,
        signal: str,
        kind: SymptomKind,
        ts: float,
        score: float,
        immediate: bool = False,
    ) -> SymptomTransition | None:
        key = (service, signal, kind)
        state = self._states.setdefault(key, _GateState())
        if state.active:
            if score <= self.config.symptom_release_score:
                state.active = False
                onset = state.onset_ts if state.onset_ts is not None else ts
                state.candidate_since = None
                state.onset_ts = None
                return SymptomTransition(
                    symptom=Symptom(
                        service=service,
                        signal=signal,
                        kind=kind,
                        onset_ts=onset,
                        score=max(0.0, min(score, 1.0)),
                    ),
                    opened=False,
                )
            return None

        if immediate or score >= self.config.symptom_enter_score:
            if state.candidate_since is None:
                state.candidate_since = ts
            sustained = ts - state.candidate_since >= self.config.symptom_sustain_s
            if immediate or sustained:
                state.active = True
                state.onset_ts = state.candidate_since
                return SymptomTransition(
                    symptom=Symptom(
                        service=service,
                        signal=signal,
                        kind=kind,
                        onset_ts=state.onset_ts,
                        score=max(0.0, min(score, 1.0)),
                    ),
                    opened=True,
                )
        else:
            state.candidate_since = None
        return None

    def residual(self, frame: DecompFrame) -> SymptomTransition | None:
        return self.update(
            service=frame.service,
            signal=frame.signal,
            kind=SymptomKind.RESIDUAL_EXCEED,
            ts=frame.ts,
            score=frame.residual_score,
        )

    def ratio(self, service: str, observation: RatioObservation) -> SymptomTransition | None:
        return self.update(
            service=service,
            signal=observation.signal,
            kind=SymptomKind.RATIO_DEFORM,
            ts=observation.onset_ts if observation.onset_ts is not None else observation.ts,
            score=observation.score,
            immediate=observation.deformed,
        )

    def log_burst(
        self,
        *,
        service: str,
        template_id: str,
        ts: float,
        score: float,
    ) -> SymptomTransition | None:
        return self.update(
            service=service,
            signal=template_id,
            kind=SymptomKind.LOG_BURST,
            ts=ts,
            score=score,
        )

    def edge_degraded(self, trace: TraceRecord, score: float) -> SymptomTransition | None:
        return self.update(
            service=trace.caller,
            signal=f"{trace.caller}->{trace.callee}",
            kind=SymptomKind.EDGE_DEGRADED,
            ts=trace.ts,
            score=score,
        )

    def saturation(
        self,
        *,
        service: str,
        signal: str,
        ts: float,
        score: float,
    ) -> SymptomTransition | None:
        return self.update(
            service=service,
            signal=signal,
            kind=SymptomKind.SATURATION,
            ts=ts,
            score=score,
        )

    def deploy(self, record: DeployRecord) -> SymptomTransition:
        transition = self.update(
            service=record.service,
            signal=record.commit,
            kind=SymptomKind.DEPLOY_MARKER,
            ts=record.ts,
            score=1.0,
            immediate=True,
        )
        if transition is None:
            raise RuntimeError("deploy pass-through must emit immediately")
        return transition
