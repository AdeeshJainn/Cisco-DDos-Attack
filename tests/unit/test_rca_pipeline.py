"""Incident clustering, causal collapse and real-history localization."""

from __future__ import annotations

import re
import subprocess

from argus.contracts import (
    DeployRecord,
    Incident,
    IncidentStatus,
    Symptom,
    SymptomKind,
    VerdictClass,
)
from argus.rca.collapse import analyze
from argus.rca.incidents import IncidentBuilder
from argus.rca.signatures import fault_signatures
from argus.scenario.faults import DEFAULT_MANIFEST_LOCK_PATH, load_fault_catalog
from argus.verdict.rules import classify


def _symptom(
    service: str,
    kind: SymptomKind,
    onset: float,
    signal: str | None = None,
) -> Symptom:
    return Symptom(
        service=service,
        signal=signal or kind,
        kind=kind,
        onset_ts=onset,
        score=0.9,
    )


def test_incident_builder_clusters_adjacent_services_and_resolves():
    builder = IncidentBuilder()
    payment = _symptom("payment-svc", SymptomKind.LOG_BURST, 100.0)
    notify = _symptom("notify-svc", SymptomKind.SATURATION, 110.0)
    auth = _symptom("auth-svc", SymptomKind.RATIO_DEFORM, 400.0)

    first = builder.ingest(payment)
    joined = builder.ingest(notify)
    separate = builder.ingest(auth)

    assert first.incident_id == joined.incident_id
    assert separate.incident_id != first.incident_id
    builder.release(
        service=payment.service,
        signal=payment.signal,
        kind=payment.kind,
        ts=200.0,
    )
    builder.release(
        service=notify.service,
        signal=notify.signal,
        kind=notify.kind,
        ts=210.0,
    )
    assert not builder.advance(269.0)
    assert builder.advance(270.0)[0].status is IncidentStatus.RESOLVED


def test_signature_library_tracks_every_real_fault():
    assert set(fault_signatures()) == set(load_fault_catalog())


def test_code_fault_collapses_to_deployed_caller_and_localizes_real_line():
    entry = load_fault_catalog()["F1"]
    deploy = DeployRecord(
        ts=100.0,
        service=entry.service,
        commit=entry.commit,
        author=entry.author,
        files=list(entry.files),
        summary=entry.summary,
    )
    incident = Incident(
        incident_id="inc-retry",
        status=IncidentStatus.OPEN,
        first_ts=120.0,
        last_ts=150.0,
        symptoms=[
            _symptom("payment-svc", SymptomKind.DEPLOY_MARKER, 100.0, entry.commit),
            _symptom("notify-svc", SymptomKind.SATURATION, 120.0, "queue_depth"),
            _symptom("payment-svc", SymptomKind.LOG_BURST, 125.0, "RETRY_STORM"),
            _symptom(
                "payment-svc",
                SymptomKind.EDGE_DEGRADED,
                130.0,
                "payment-svc->notify-svc",
            ),
        ],
    )
    result = analyze(incident, classify(incident), [deploy])

    assert result.origin.service == "payment-svc"
    assert result.code_fault is not None
    assert result.code_fault.commit == entry.commit
    assert result.code_fault.file == entry.file
    assert result.code_fault.line == entry.line
    assert result.code_fault.proposed_fix is not None
    source = subprocess.check_output(
        [
            "git",
            "-C",
            str(DEFAULT_MANIFEST_LOCK_PATH.parent),
            "show",
            f"{entry.commit}:{entry.file}",
        ],
        text=True,
    ).splitlines()
    assert re.search(entry.pattern, source[entry.line - 1])


def test_attack_rca_has_one_origin_reason_and_no_code_claim():
    incident = Incident(
        incident_id="inc-attack",
        status=IncidentStatus.OPEN,
        first_ts=100.0,
        last_ts=130.0,
        symptoms=[
            _symptom("auth-svc", SymptomKind.RESIDUAL_EXCEED, 100.0, "rps"),
            _symptom("auth-svc", SymptomKind.RATIO_DEFORM, 105.0, "auth_fail_ratio"),
        ],
    )
    verdict = classify(incident)
    result = analyze(incident, verdict, [])
    top = max(verdict.classes, key=lambda item: item.p).verdict_class

    assert top is VerdictClass.ATTACK
    assert result.origin.service == "auth-svc"
    assert result.code_fault is None
    assert result.collapse_trace
    assert result.cure.justification
