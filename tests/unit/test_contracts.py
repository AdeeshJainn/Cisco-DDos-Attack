"""Contract fixtures are the documentation wire examples: every schema has
exactly one fixture that round-trips parse → dump → parse identically, and
malformed payloads (blank reasons, empty evidence, broken orderings) are
rejected by the model validators."""

import json
from pathlib import Path

import pytest
from argus import contracts as c
from pydantic import ValidationError

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"

# Scenario-file record kinds → the fixture (and registry) name of their model.
SCENARIO_LINE_FIXTURES = {
    "header": "scenario_header",
    "metric": "metric_record",
    "net": "net_record",
    "log": "log_record",
    "trace": "trace_record",
    "calendar": "calendar_record",
    "deploy": "deploy_record",
}


def load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


# --- fixture coverage and round-trips ----------------------------------------


def test_every_schema_has_exactly_one_fixture():
    on_disk = {path.stem for path in FIXTURES_DIR.glob("*.json")}
    assert on_disk == set(c.CONTRACT_MODELS)


@pytest.mark.parametrize("name", sorted(c.CONTRACT_MODELS))
def test_fixture_round_trips(name):
    fixture = load(name)
    model = c.CONTRACT_MODELS[name]
    first = model.model_validate(fixture)
    dumped = first.model_dump(mode="json")
    assert dumped == fixture, "dump must match the documented wire example"
    assert model.model_validate(dumped) == first


@pytest.mark.parametrize(("kind", "fixture_name"), sorted(SCENARIO_LINE_FIXTURES.items()))
def test_scenario_line_union_discriminates(kind, fixture_name):
    parsed = c.parse_scenario_line(json.dumps(load(fixture_name)))
    assert parsed.kind == kind
    assert isinstance(parsed, c.CONTRACT_MODELS[fixture_name])


def test_labels_expose_the_class_alias_as_incident_class():
    labels = c.GroundTruthLabels.model_validate(load("ground_truth_labels"))
    assert labels.incidents[0].incident_class is c.IncidentClass.ATTACK
    assert "class" in labels.model_dump(mode="json")["incidents"][0]


# --- websocket envelope: both discriminator axes ----------------------------


def _envelope(payload):
    return {"seq": 10452, "wall_ts": 1789460010.211, "sim_ts": 1789455631.0, "payload": payload}


def test_envelope_carries_engine_payloads():
    env = c.WsEnvelope.model_validate(load("ws_envelope"))
    assert isinstance(env.payload, c.Verdict)


def test_envelope_carries_telemetry_ticks():
    env = c.WsEnvelope.model_validate(_envelope(load("metric_record")))
    assert isinstance(env.payload, c.MetricRecord)


def test_envelope_carries_control_payloads():
    clock = c.WsEnvelope.model_validate(_envelope(load("clock_payload"))).payload
    assert isinstance(clock, c.ClockPayload)
    approval = c.WsEnvelope.model_validate(_envelope(load("approval_request"))).payload
    assert isinstance(approval, c.ApprovalRequestPayload)
    assert isinstance(approval.proposed_action, c.Action)


def test_envelope_rejects_unknown_payload_type():
    with pytest.raises(ValidationError):
        c.WsEnvelope.model_validate(_envelope({"type": "mystery"}))


# --- validators reject malformed payloads -----------------------------------


def test_header_rejects_unordered_spans():
    header = load("scenario_header")
    bad = {**header, "scored_from_ts": header["end_ts"] + 1}
    with pytest.raises(ValidationError, match="precedes"):
        c.ScenarioHeader.model_validate(bad)


def test_labels_require_code_fault_details_for_code_fault_class():
    code_fault_incident = load("ground_truth_labels")["incidents"][1]
    assert code_fault_incident["class"] == "code_fault"
    with pytest.raises(ValidationError, match="code_fault"):
        c.GroundTruthIncident.model_validate({**code_fault_incident, "code_fault": None})


def test_decomp_rejects_reversed_band():
    decomp = load("decomp_frame")
    with pytest.raises(ValidationError, match="precedes"):
        c.DecompFrame.model_validate({**decomp, "band": list(reversed(decomp["band"]))})


def test_decomp_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        c.DecompFrame.model_validate({**load("decomp_frame"), "residual_score": 1.2})


def test_incident_requires_symptoms():
    with pytest.raises(ValidationError):
        c.Incident.model_validate({**load("incident"), "symptoms": []})


def test_incident_rejects_reversed_window():
    incident = load("incident")
    bad = {**incident, "first_ts": incident["last_ts"], "last_ts": incident["first_ts"]}
    with pytest.raises(ValidationError, match="precedes"):
        c.Incident.model_validate(bad)


def test_verdict_requires_evidence():
    with pytest.raises(ValidationError):
        c.Verdict.model_validate({**load("verdict"), "evidence": []})


def test_verdict_rejects_probabilities_not_summing_to_one():
    bad_classes = [{"class": "attack", "p": 0.5}, {"class": "expected_surge", "p": 0.1}]
    with pytest.raises(ValidationError, match="sum"):
        c.Verdict.model_validate({**load("verdict"), "classes": bad_classes})


def test_verdict_rejects_duplicate_classes():
    bad_classes = [{"class": "attack", "p": 0.5}, {"class": "attack", "p": 0.5}]
    with pytest.raises(ValidationError, match="repeat"):
        c.Verdict.model_validate({**load("verdict"), "classes": bad_classes})


def test_rca_code_fault_requires_finding():
    with pytest.raises(ValidationError, match="code_fault"):
        c.RcaResult.model_validate({**load("rca_result"), "code_fault": None})


def test_rca_attack_cause_needs_no_finding():
    ok = {**load("rca_result"), "cause_class": "attack", "code_fault": None}
    assert c.RcaResult.model_validate(ok).code_fault is None


def test_decision_rejects_blank_reason():
    with pytest.raises(ValidationError, match="blank"):
        c.Decision.model_validate({**load("decision"), "reason": "   "})


def test_human_gate_requires_complete_approval():
    bad_gate = {"required": True, "approved_by": "yash", "approved_ts": None}
    with pytest.raises(ValidationError, match="together"):
        c.HumanGate.model_validate(bad_gate)


def test_action_rejects_traffic_pct_over_100():
    action = load("action")
    bad_target = {**action["target"], "est_traffic_pct": 150.0}
    with pytest.raises(ValidationError):
        c.Action.model_validate({**action, "target": bad_target})


def test_rollback_requires_verification():
    bad = {key: value for key, value in load("rollback").items() if key != "verification"}
    with pytest.raises(ValidationError):
        c.Rollback.model_validate(bad)


def test_mttr_rejects_unordered_lifecycle():
    mttr = load("mttr_record")
    bad = {**mttr, "detected_ts": mttr["root_caused_ts"], "root_caused_ts": mttr["detected_ts"]}
    with pytest.raises(ValidationError, match="precedes"):
        c.MttrRecord.model_validate(bad)


def test_mttr_rejects_inconsistent_autonomous_seconds():
    with pytest.raises(ValidationError, match="disagrees"):
        c.MttrRecord.model_validate({**load("mttr_record"), "autonomous_s": 9000})


# --- shared ordering helper --------------------------------------------------


def test_ensure_ordered_accepts_equal_timestamps():
    c.ensure_ordered([("a", 1.0), ("b", 1.0), ("c", 2.0)])


def test_ensure_ordered_names_the_offending_pair():
    with pytest.raises(ValueError, match=r"b \(1\.0\) precedes a \(2\.0\)"):
        c.ensure_ordered([("a", 2.0), ("b", 1.0)])
