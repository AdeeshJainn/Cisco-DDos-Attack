"""Contract models: documented wire examples parse and round-trip; malformed
payloads (blank reasons, empty evidence, broken orderings) are rejected."""

import json

import pytest
from argus import contracts as c
from pydantic import ValidationError

# A realistic stand-in for a materialized demo-app commit hash.
COMMIT = "b7c9d2e4f6a81035c7e9d2b4a6f81023c5e7a9b1"

SCENARIO_LINES = {
    "header": {
        "kind": "header",
        "contract": "v0.2",
        "seed": 424242,
        "profile": "match_night",
        "start_ts": 1789257600,
        "scored_from_ts": 1789430400,
        "end_ts": 1789516800,
        "resolution_s": 1,
        "warmup_resolution_s": 60,
        "services": ["edge-gw", "auth-svc", "catalog-svc", "payment-svc", "notify-svc"],
        "demo_app_manifest": ".manifest.lock.json",
    },
    "metric": {
        "kind": "metric",
        "ts": 1789430401,
        "service": "edge-gw",
        "name": "rps",
        "value": 1832.0,
    },
    "net": {
        "kind": "net",
        "ts": 1789430401,
        "service": "edge-gw",
        "uniq_ip_entropy": 7.9,
        "syn_ack_ratio": 1.02,
        "auth_fail_ratio": 0.011,
        "ja3_novelty": 0.03,
        "geo_top1_share": 0.22,
    },
    "log": {
        "kind": "log",
        "ts": 1789430402,
        "service": "payment-svc",
        "level": "error",
        "template_id": "TIMEOUT_DOWNSTREAM",
        "msg": "timeout calling notify-svc",
        "count": 17,
    },
    "trace": {
        "kind": "trace",
        "ts": 1789430402,
        "caller": "payment-svc",
        "callee": "notify-svc",
        "rps": 240.0,
        "err_rate": 0.31,
        "p99_ms": 4200,
    },
    "calendar": {
        "kind": "calendar",
        "ts": 1789452000,
        "event_id": "match-final",
        "title": "Cup Final",
        "phase": "start",
        "expected_multiplier": 6.5,
        "affects": ["edge-gw", "auth-svc", "catalog-svc"],
    },
    "deploy": {
        "kind": "deploy",
        "ts": 1789445000,
        "service": "payment-svc",
        "commit": COMMIT,
        "author": "arjun",
        "files": ["payment_svc/retry.py"],
        "summary": "tune retry behavior",
    },
}

LABELS = {
    "contract": "v0.2",
    "seed": 424242,
    "incidents": [
        {
            "gt_id": "gt-1",
            "class": "attack",
            "sub_type": "app_layer_flood",
            "window": [1789455600, 1789459200],
            "origin_service": "edge-gw",
            "inside_event": "match-final",
            "correct_decision": "act",
            "reason_category": "behavioral_deformation",
            "code_fault": None,
        },
        {
            "gt_id": "gt-2",
            "class": "code_fault",
            "sub_type": "retry_storm",
            "window": [1789460000, 1789463000],
            "origin_service": "payment-svc",
            "inside_event": None,
            "correct_decision": "act",
            "reason_category": "deploy_correlated_cascade",
            "code_fault": {
                "commit": COMMIT,
                "file": "payment_svc/retry.py",
                "line": 42,
                "mechanism": "unbounded_retry_no_backoff",
            },
        },
    ],
    "timestep_labels_file": "match_night.steplabels.parquet",
}

DECOMP = {
    "type": "decomp",
    "ts": 1789455610,
    "service": "edge-gw",
    "signal": "rps",
    "observed": 14200.0,
    "explained_base": 1900.0,
    "explained_event": 10100.0,
    "residual": 2200.0,
    "band": [11400.0, 12600.0],
    "residual_score": 0.93,
}

INCIDENT = {
    "type": "incident",
    "incident_id": "inc-007",
    "status": "open",
    "first_ts": 1789455600,
    "last_ts": 1789455900,
    "symptoms": [
        {
            "service": "edge-gw",
            "signal": "rps",
            "kind": "residual_exceed",
            "onset_ts": 1789455600,
            "score": 0.93,
        },
        {
            "service": "edge-gw",
            "signal": "syn_ack_ratio",
            "kind": "ratio_deform",
            "onset_ts": 1789455605,
            "score": 0.88,
        },
        {
            "service": "auth-svc",
            "signal": "auth_fail_ratio",
            "kind": "ratio_deform",
            "onset_ts": 1789455620,
            "score": 0.91,
        },
    ],
}

VERDICT = {
    "type": "verdict",
    "incident_id": "inc-007",
    "classes": [
        {"class": "attack", "p": 0.87},
        {"class": "expected_surge", "p": 0.09},
        {"class": "operational_fault", "p": 0.02},
        {"class": "code_fault", "p": 0.02},
    ],
    "combination": False,
    "confidence": 0.87,
    "evidence": [
        {
            "feature": "ja3_novelty",
            "value": 0.41,
            "baseline": 0.03,
            "direction": "up",
            "note": "new client fingerprints inside event window",
        },
        {
            "feature": "uniq_ip_entropy",
            "value": 4.1,
            "baseline": 7.8,
            "direction": "down",
            "note": "traffic concentration inconsistent with organic fan surge",
        },
    ],
}

RCA = {
    "type": "rca",
    "incident_id": "inc-009",
    "origin": {
        "service": "payment-svc",
        "onset_ts": 1789460010,
        "alternates": [{"service": "notify-svc", "score": 0.31}],
    },
    "cause_class": "code_fault",
    "collapse_trace": [
        "notify-svc p99 rose AFTER payment-svc→notify-svc rps ×38 (amplification at caller)",
        "deploy b7c9d2e4 on payment-svc 4m before onset touched retry.py",
        "log template TIMEOUT_DOWNSTREAM count correlates with retry loop period",
    ],
    "code_fault": {
        "commit": COMMIT,
        "file": "payment_svc/retry.py",
        "line": 42,
        "function": "call_notify",
        "config_value": "max_retries=0 (unbounded)",
        "mechanism": (
            "timeout triggers immediate re-send with no backoff; "
            "each failure multiplies downstream load"
        ),
        "proposed_fix": {
            "summary": "cap retries + exponential backoff + circuit breaker",
            "diff": "--- a/payment_svc/retry.py\n+++ b/payment_svc/retry.py\n@@ -40,3 +40,6 @@\n",
        },
    },
    "cure": {
        "kind": "code_fix",
        "justification": "infra scaling would feed the storm; origin is deploy-correlated",
        "interim_infra_action": "throttle payment-svc→notify-svc client to pre-deploy rate",
    },
    "confidence": 0.83,
}

DECISION = {
    "type": "decision",
    "decision_id": "dec-021",
    "incident_id": "inc-007",
    "ts": 1789455630,
    "decision": "act",
    "reason": (
        "volume explained by match-final EXCEPT residual with deformed ratios; "
        "residual cohort identified"
    ),
    "evidence_ref": "inc-007/verdict",
    "confidence": 0.87,
    "human_gate": {"required": False, "approved_by": None, "approved_ts": None},
}

ACTION = {
    "type": "action",
    "action_id": "act-034",
    "decision_id": "dec-021",
    "ts": 1789455631,
    "rung": "rate_limit",
    "target": {"kind": "cohort", "selector": "ja3_novel AND geo_top1", "est_traffic_pct": 11.2},
    "blast_radius": {
        "protected_cohorts_touched": 0,
        "max_pct_allowed": 15.0,
        "gates_passed": ["confidence>=0.6", "protected_untouched", "dwell_observe>=60s"],
    },
    "trigger": "verdict attack p=0.87 + residual_score 0.93",
    "expected_effect": "residual rps -60% within 120s, event traffic unaffected",
}

ROLLBACK = {
    "type": "rollback",
    "rollback_id": "rb-002",
    "action_id": "act-034",
    "ts": 1789455811,
    "trigger": "auto",
    "cause": "legit err_rate rose 0.4%→1.9% for protected cohort",
    "reverted": True,
    "verification": {
        "users_restored": True,
        "checked_signals": ["err_rate", "p95_ms"],
        "verified_ts": 1789455871,
    },
}

MTTR = {
    "type": "mttr",
    "incident_id": "inc-009",
    "onset_ts": 1789460010,
    "detected_ts": 1789460022,
    "root_caused_ts": 1789460041,
    "mitigated_ts": 1789460060,
    "verified_ts": 1789460180,
    "manual_baseline_s": 14400,
    "autonomous_s": 170,
}

CLOCK = {"type": "clock", "speed": 60, "state": "playing", "sim_ts": 1789455631.0}

APPROVAL = {
    "type": "approval_request",
    "decision_id": "dec-022",
    "proposed_action": ACTION,
    "timeout_s": 120,
}

PAYLOAD_EXAMPLES = {
    c.DecompFrame: DECOMP,
    c.Incident: INCIDENT,
    c.Verdict: VERDICT,
    c.RcaResult: RCA,
    c.Decision: DECISION,
    c.Action: ACTION,
    c.Rollback: ROLLBACK,
    c.MttrRecord: MTTR,
    c.ClockPayload: CLOCK,
    c.ApprovalRequestPayload: APPROVAL,
}


# --- documented examples parse and round-trip -------------------------------


@pytest.mark.parametrize("kind", sorted(SCENARIO_LINES))
def test_scenario_line_round_trips(kind):
    parsed = c.parse_scenario_line(json.dumps(SCENARIO_LINES[kind]))
    assert parsed.kind == kind
    assert parsed.model_dump(mode="json") == SCENARIO_LINES[kind]


@pytest.mark.parametrize("model", PAYLOAD_EXAMPLES, ids=lambda m: m.__name__)
def test_engine_payload_round_trips(model):
    example = PAYLOAD_EXAMPLES[model]
    parsed = model.model_validate(example)
    assert parsed.model_dump(mode="json") == example


def test_labels_round_trip_with_class_alias():
    labels = c.GroundTruthLabels.model_validate(LABELS)
    assert labels.incidents[0].incident_class is c.IncidentClass.ATTACK
    dumped = labels.model_dump(mode="json")
    assert dumped == LABELS
    assert "class" in dumped["incidents"][0]  # wire name, not the python name


def test_verdict_dump_uses_class_alias():
    dumped = c.Verdict.model_validate(VERDICT).model_dump(mode="json")
    assert dumped["classes"][0] == {"class": "attack", "p": 0.87}


# --- websocket envelope: both discriminator axes ----------------------------


def _envelope(payload):
    return {"seq": 10452, "wall_ts": 1789460010.211, "sim_ts": 1789455631.0, "payload": payload}


def test_envelope_carries_engine_payloads():
    env = c.WsEnvelope.model_validate(_envelope(VERDICT))
    assert isinstance(env.payload, c.Verdict)


def test_envelope_carries_telemetry_ticks():
    env = c.WsEnvelope.model_validate(_envelope(SCENARIO_LINES["metric"]))
    assert isinstance(env.payload, c.MetricRecord)


def test_envelope_carries_control_payloads():
    assert isinstance(c.WsEnvelope.model_validate(_envelope(CLOCK)).payload, c.ClockPayload)
    approval = c.WsEnvelope.model_validate(_envelope(APPROVAL)).payload
    assert isinstance(approval, c.ApprovalRequestPayload)
    assert isinstance(approval.proposed_action, c.Action)


def test_envelope_rejects_unknown_payload_type():
    with pytest.raises(ValidationError):
        c.WsEnvelope.model_validate(_envelope({"type": "mystery"}))


# --- validators reject malformed payloads -----------------------------------


def test_header_rejects_unordered_spans():
    bad = {**SCENARIO_LINES["header"], "scored_from_ts": SCENARIO_LINES["header"]["end_ts"] + 1}
    with pytest.raises(ValidationError, match="precedes"):
        c.ScenarioHeader.model_validate(bad)


def test_labels_require_code_fault_details_for_code_fault_class():
    bad_incident = {**LABELS["incidents"][1], "code_fault": None}
    with pytest.raises(ValidationError, match="code_fault"):
        c.GroundTruthIncident.model_validate(bad_incident)


def test_decomp_rejects_reversed_band():
    with pytest.raises(ValidationError, match="precedes"):
        c.DecompFrame.model_validate({**DECOMP, "band": [12600.0, 11400.0]})


def test_decomp_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        c.DecompFrame.model_validate({**DECOMP, "residual_score": 1.2})


def test_incident_requires_symptoms():
    with pytest.raises(ValidationError):
        c.Incident.model_validate({**INCIDENT, "symptoms": []})


def test_incident_rejects_reversed_window():
    bad = {**INCIDENT, "first_ts": INCIDENT["last_ts"], "last_ts": INCIDENT["first_ts"]}
    with pytest.raises(ValidationError, match="precedes"):
        c.Incident.model_validate(bad)


def test_verdict_requires_evidence():
    with pytest.raises(ValidationError):
        c.Verdict.model_validate({**VERDICT, "evidence": []})


def test_verdict_rejects_probabilities_not_summing_to_one():
    bad_classes = [{"class": "attack", "p": 0.5}, {"class": "expected_surge", "p": 0.1}]
    with pytest.raises(ValidationError, match="sum"):
        c.Verdict.model_validate({**VERDICT, "classes": bad_classes})


def test_verdict_rejects_duplicate_classes():
    bad_classes = [{"class": "attack", "p": 0.5}, {"class": "attack", "p": 0.5}]
    with pytest.raises(ValidationError, match="repeat"):
        c.Verdict.model_validate({**VERDICT, "classes": bad_classes})


def test_rca_code_fault_requires_finding():
    with pytest.raises(ValidationError, match="code_fault"):
        c.RcaResult.model_validate({**RCA, "code_fault": None})


def test_rca_attack_cause_needs_no_finding():
    ok = {**RCA, "cause_class": "attack", "code_fault": None}
    assert c.RcaResult.model_validate(ok).code_fault is None


def test_decision_rejects_blank_reason():
    with pytest.raises(ValidationError, match="blank"):
        c.Decision.model_validate({**DECISION, "reason": "   "})


def test_human_gate_requires_complete_approval():
    bad_gate = {"required": True, "approved_by": "yash", "approved_ts": None}
    with pytest.raises(ValidationError, match="together"):
        c.HumanGate.model_validate(bad_gate)


def test_action_rejects_traffic_pct_over_100():
    bad_target = {**ACTION["target"], "est_traffic_pct": 150.0}
    with pytest.raises(ValidationError):
        c.Action.model_validate({**ACTION, "target": bad_target})


def test_rollback_requires_verification():
    bad = {key: value for key, value in ROLLBACK.items() if key != "verification"}
    with pytest.raises(ValidationError):
        c.Rollback.model_validate(bad)


def test_mttr_rejects_unordered_lifecycle():
    bad = {**MTTR, "detected_ts": MTTR["root_caused_ts"], "root_caused_ts": MTTR["detected_ts"]}
    with pytest.raises(ValidationError, match="precedes"):
        c.MttrRecord.model_validate(bad)


def test_mttr_rejects_inconsistent_autonomous_seconds():
    with pytest.raises(ValidationError, match="disagrees"):
        c.MttrRecord.model_validate({**MTTR, "autonomous_s": 9000})


# --- shared ordering helper --------------------------------------------------


def test_ensure_ordered_accepts_equal_timestamps():
    c.ensure_ordered([("a", 1.0), ("b", 1.0), ("c", 2.0)])


def test_ensure_ordered_names_the_offending_pair():
    with pytest.raises(ValueError, match=r"b \(1\.0\) precedes a \(2\.0\)"):
        c.ensure_ordered([("a", 2.0), ("b", 1.0)])
