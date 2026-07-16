"""Ordered rule-table classifier; every rule emits its evidence."""

from __future__ import annotations

import numpy as np

from argus.config import CONFIG, VerdictConfig
from argus.contracts import (
    ClassProbability,
    Direction,
    EvidenceItem,
    Incident,
    Symptom,
    SymptomKind,
    Verdict,
    VerdictClass,
)

_EVIDENCE_NOTES = {
    SymptomKind.RESIDUAL_EXCEED: "observed volume exceeds the context-aware expected band",
    SymptomKind.RATIO_DEFORM: "load-invariant client behavior moved outside its robust baseline",
    SymptomKind.LOG_BURST: "an error template burst corroborates service degradation",
    SymptomKind.EDGE_DEGRADED: "dependency-edge latency or errors rose above baseline",
    SymptomKind.SATURATION: "resource pressure indicates an internal capacity constraint",
    SymptomKind.DEPLOY_MARKER: "a recent deploy precedes the symptom cascade",
}


def _confidence(
    symptoms: list[Symptom],
    config: VerdictConfig,
) -> float:
    average_score = float(np.mean([symptom.score for symptom in symptoms]))
    corroboration = min(len(symptoms), config.max_corroborating_symptoms)
    return float(
        np.clip(
            config.confidence_floor
            + config.evidence_score_gain * average_score
            + config.corroboration_gain * (corroboration - 1),
            config.confidence_floor,
            config.confidence_cap,
        )
    )


def _distribution(
    primary: VerdictClass,
    confidence: float,
) -> list[ClassProbability]:
    classes = list(VerdictClass)
    remainder = (1.0 - confidence) / (len(classes) - 1)
    return [
        ClassProbability(
            verdict_class=verdict_class,
            p=confidence if verdict_class is primary else remainder,
        )
        for verdict_class in classes
    ]


def _combination_distribution(confidence: float) -> list[ClassProbability]:
    primary = confidence / 2.0
    secondary = (1.0 - confidence) / 2.0
    return [
        ClassProbability(
            verdict_class=verdict_class,
            p=primary
            if verdict_class in {VerdictClass.ATTACK, VerdictClass.CODE_FAULT}
            else secondary,
        )
        for verdict_class in VerdictClass
    ]


def _evidence(symptoms: list[Symptom]) -> list[EvidenceItem]:
    return [
        EvidenceItem(
            feature=f"{symptom.service}.{symptom.signal}",
            value=symptom.score,
            baseline=0.0,
            direction=Direction.UP,
            note=_EVIDENCE_NOTES[symptom.kind],
        )
        for symptom in sorted(
            symptoms,
            key=lambda item: (-item.score, item.onset_ts, item.service, item.signal),
        )
    ]


def classify(
    incident: Incident,
    *,
    event_explained: bool = False,
    config: VerdictConfig = CONFIG.verdict,
) -> Verdict:
    """Apply the v0 rule table in priority order with scored reasons."""
    kinds = {symptom.kind for symptom in incident.symptoms}
    has_ratio = SymptomKind.RATIO_DEFORM in kinds
    has_deploy = SymptomKind.DEPLOY_MARKER in kinds
    has_internal = bool(
        kinds
        & {
            SymptomKind.LOG_BURST,
            SymptomKind.EDGE_DEGRADED,
            SymptomKind.SATURATION,
        }
    )
    confidence = _confidence(incident.symptoms, config)

    if has_ratio and has_deploy:
        classes = _combination_distribution(confidence)
        combination = True
    elif has_ratio:
        classes = _distribution(VerdictClass.ATTACK, confidence)
        combination = False
    elif has_deploy and has_internal:
        classes = _distribution(VerdictClass.CODE_FAULT, confidence)
        combination = False
    elif has_internal:
        classes = _distribution(VerdictClass.OPERATIONAL_FAULT, confidence)
        combination = False
    elif event_explained:
        classes = _distribution(VerdictClass.EXPECTED_SURGE, confidence)
        combination = False
    else:
        classes = _distribution(VerdictClass.OPERATIONAL_FAULT, confidence)
        combination = False

    return Verdict(
        incident_id=incident.incident_id,
        classes=classes,
        combination=combination,
        confidence=confidence,
        evidence=_evidence(incident.symptoms),
    )
