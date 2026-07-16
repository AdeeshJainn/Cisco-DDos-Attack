"""Interpretable causal collapse and frozen-contract RCA assembly."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from argus.config import CONFIG, RcaConfig
from argus.contracts import (
    AlternateOrigin,
    CauseClass,
    Cure,
    CureKind,
    DeployRecord,
    Incident,
    RcaOrigin,
    RcaResult,
    Verdict,
    VerdictClass,
)
from argus.scenario.base import DEFAULT_TOPOLOGY_PATH

from .incidents import topology_graph
from .localize import localize
from .signatures import signature_strength


@dataclass(frozen=True)
class CandidateScore:
    service: str
    onset_ts: float
    onset: float
    propagation: float
    deploy: float
    signature: float
    total: float


def _cause(verdict: Verdict) -> CauseClass:
    if verdict.combination:
        return CauseClass.COMBINATION
    top = max(verdict.classes, key=lambda item: item.p).verdict_class
    mapping = {
        VerdictClass.ATTACK: CauseClass.ATTACK,
        VerdictClass.OPERATIONAL_FAULT: CauseClass.OPERATIONAL_FAULT,
        VerdictClass.CODE_FAULT: CauseClass.CODE_FAULT,
    }
    if top not in mapping:
        raise ValueError("expected surges are explained context and do not require RCA")
    return mapping[top]


def collapse(
    incident: Incident,
    verdict: Verdict,
    deploys: list[DeployRecord],
    *,
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
    config: RcaConfig = CONFIG.rca,
) -> tuple[CauseClass, list[CandidateScore], list[str]]:
    cause_class = _cause(verdict)
    graph = topology_graph(topology_path)
    symptomatic = {symptom.service for symptom in incident.symptoms}
    candidates = symptomatic | {
        neighbor for service in symptomatic for neighbor in graph.get(service, ())
    }
    service_onsets = {
        service: min(
            symptom.onset_ts for symptom in incident.symptoms if symptom.service == service
        )
        for service in symptomatic
    }
    earliest = min(service_onsets.values())
    latest = max(service_onsets.values())
    span = max(latest - earliest, config.incident_gap_s)
    kinds = {symptom.kind for symptom in incident.symptoms}
    signature = signature_strength(cause_class, kinds)
    scored = []
    for service in candidates:
        onset_ts = service_onsets.get(service, incident.first_ts)
        onset_score = (
            max(0.0, 1.0 - (onset_ts - earliest) / span) if service in service_onsets else 0.0
        )
        propagation = (
            sum(
                symptom.onset_ts >= onset_ts
                for symptom in incident.symptoms
                if symptom.service != service
            )
            / max(
                1,
                sum(symptom.service != service for symptom in incident.symptoms),
            )
            if service in service_onsets
            else 0.0
        )
        deploy_score = max(
            (
                math.exp(-(incident.first_ts - deploy.ts) / config.deploy_decay_s)
                for deploy in deploys
                if deploy.service == service and deploy.ts <= incident.first_ts
            ),
            default=0.0,
        )
        service_signature = signature if service in symptomatic else 0.0
        total = (
            config.onset_weight * onset_score
            + config.propagation_weight * propagation
            + config.deploy_weight * deploy_score
            + config.signature_weight * service_signature
        )
        scored.append(
            CandidateScore(
                service=service,
                onset_ts=onset_ts,
                onset=onset_score,
                propagation=propagation,
                deploy=deploy_score,
                signature=service_signature,
                total=total,
            )
        )
    scored.sort(key=lambda item: (-item.total, item.onset_ts, item.service))
    winner = scored[0]
    trace = [
        (
            f"{winner.service} ranked first: onset={winner.onset:.2f}, "
            f"propagation={winner.propagation:.2f}, deploy={winner.deploy:.2f}, "
            f"signature={winner.signature:.2f}"
        ),
        *[
            (
                f"{symptom.service}.{symptom.signal} {symptom.kind} "
                f"opened at {symptom.onset_ts:.0f} with score {symptom.score:.2f}"
            )
            for symptom in sorted(
                incident.symptoms,
                key=lambda item: (item.onset_ts, item.service, item.signal),
            )
        ],
    ]
    return cause_class, scored, trace


def analyze(
    incident: Incident,
    verdict: Verdict,
    deploys: list[DeployRecord],
    *,
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
    config: RcaConfig = CONFIG.rca,
) -> RcaResult:
    cause_class, scored, trace = collapse(
        incident,
        verdict,
        deploys,
        topology_path=topology_path,
        config=config,
    )
    winner = scored[0]
    finding = (
        localize(
            service=winner.service,
            onset_ts=incident.first_ts,
            deploys=deploys,
            config=config,
        )
        if cause_class is CauseClass.CODE_FAULT
        else None
    )
    return RcaResult(
        incident_id=incident.incident_id,
        origin=RcaOrigin(
            service=winner.service,
            onset_ts=winner.onset_ts,
            alternates=[
                AlternateOrigin(service=item.service, score=max(0.0, min(item.total, 1.0)))
                for item in scored[1:]
            ],
        ),
        cause_class=cause_class,
        collapse_trace=trace,
        code_fault=finding,
        cure=_cure(cause_class, winner.service),
        confidence=max(0.0, min(winner.total, 1.0)),
    )


def _cure(cause_class: CauseClass, service: str) -> Cure:
    if cause_class is CauseClass.CODE_FAULT:
        return Cure(
            kind=CureKind.CODE_FIX,
            justification=(
                "A deploy-correlated code mechanism explains the cascade; "
                "adding capacity alone could amplify the failure."
            ),
            interim_infra_action=f"throttle callers to {service} to the pre-deploy rate",
        )
    if cause_class is CauseClass.ATTACK:
        return Cure(
            kind=CureKind.INFRA_ACTION,
            justification=(
                "Behavioral deformation identifies a suspect traffic cohort "
                "while legitimate volume remains serviceable."
            ),
            interim_infra_action=f"rate-limit the anomalous cohort at {service}",
        )
    return Cure(
        kind=CureKind.INFRA_ACTION,
        justification=(
            "Internal degradation without deploy evidence calls for a reversible "
            "service runbook action."
        ),
        interim_infra_action=f"scale or reroute {service} while watching recovery",
    )
