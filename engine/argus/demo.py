"""Seeded demonstration snapshot assembled through the reasoning modules."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from argus.audit.reports import report_markdown
from argus.contracts import Incident, IncidentStatus, Symptom, SymptomKind
from argus.policy.decide import decide
from argus.policy.ladder import first_action
from argus.rca.collapse import analyze
from argus.scenario.faults import deploy_record, load_fault_catalog
from argus.scenario.generate import DEFAULT_SCORED_FROM_TS
from argus.scenario.profiles import build_profile
from argus.verdict.rules import classify


def _symptom(
    service: str,
    signal: str,
    kind: SymptomKind,
    onset_ts: float,
    score: float,
) -> Symptom:
    return Symptom(
        service=service,
        signal=signal,
        kind=kind,
        onset_ts=onset_ts,
        score=score,
    )


@lru_cache(maxsize=1)
def build_demo_snapshot() -> dict:
    plan = build_profile("combo_night", DEFAULT_SCORED_FROM_TS)
    attack = plan.attacks[0]
    event = plan.events[0]
    fault = plan.code_faults[0]
    deploy = deploy_record(load_fault_catalog()[fault.fault_id], fault)

    attack_incident = Incident(
        incident_id="inc-attack",
        status=IncidentStatus.OPEN,
        first_ts=attack.start_ts,
        last_ts=attack.start_ts + 45.0,
        symptoms=[
            _symptom(
                attack.target_service,
                "rps",
                SymptomKind.RESIDUAL_EXCEED,
                attack.start_ts,
                0.93,
            ),
            _symptom(
                attack.target_service,
                "auth_fail_ratio",
                SymptomKind.RATIO_DEFORM,
                attack.start_ts + 31.0,
                0.96,
            ),
        ],
    )
    attack_verdict = classify(attack_incident)
    attack_rca = analyze(attack_incident, attack_verdict, [])
    attack_decision = decide(attack_verdict, ts=attack_incident.last_ts)
    attack_action = first_action(
        attack_decision,
        attack_verdict,
        ts=attack_incident.last_ts + 1.0,
    )

    fault_incident = Incident(
        incident_id="inc-retry-storm",
        status=IncidentStatus.OPEN,
        first_ts=fault.onset_ts,
        last_ts=fault.onset_ts + 45.0,
        symptoms=[
            _symptom(
                deploy.service,
                deploy.commit,
                SymptomKind.DEPLOY_MARKER,
                deploy.ts,
                1.0,
            ),
            _symptom(
                "notify-svc",
                "queue_depth",
                SymptomKind.SATURATION,
                fault.onset_ts,
                0.91,
            ),
            _symptom(
                deploy.service,
                "RETRY_STORM",
                SymptomKind.LOG_BURST,
                fault.onset_ts + 8.0,
                0.94,
            ),
            _symptom(
                deploy.service,
                "payment-svc->notify-svc",
                SymptomKind.EDGE_DEGRADED,
                fault.onset_ts + 12.0,
                0.92,
            ),
        ],
    )
    fault_verdict = classify(fault_incident)
    fault_rca = analyze(fault_incident, fault_verdict, [deploy])
    fault_decision = decide(fault_verdict, ts=fault_incident.last_ts)

    points = np.linspace(0.0, 1.0, 36)
    event_curve = np.sin(np.pi * points) ** 2 * (event.multiplier - 1.0)
    residual = np.exp(-(((points - 0.58) / 0.10) ** 2)) * attack.rps_multiplier
    base = np.full(len(points), 1.0)

    return {
        "mode": "seeded deterministic simulation",
        "profile": plan.name,
        "seed": 424242,
        "timeline": {
            "labels": [f"{17 + index / 12:.1f}h" for index in range(len(points))],
            "base": base.tolist(),
            "event": event_curve.tolist(),
            "residual": residual.tolist(),
            "observed": (base + event_curve + residual).tolist(),
        },
        "incidents": [
            {
                "incident": attack_incident.model_dump(mode="json"),
                "verdict": attack_verdict.model_dump(mode="json"),
                "rca": attack_rca.model_dump(mode="json"),
                "decision": attack_decision.model_dump(mode="json"),
                "action": (
                    attack_action.model_dump(mode="json") if attack_action is not None else None
                ),
            },
            {
                "incident": fault_incident.model_dump(mode="json"),
                "verdict": fault_verdict.model_dump(mode="json"),
                "rca": fault_rca.model_dump(mode="json"),
                "decision": fault_decision.model_dump(mode="json"),
                "action": None,
                "report": report_markdown(fault_incident, fault_verdict, fault_rca),
            },
        ],
    }
