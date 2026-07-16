"""P3.6 profile composition, deterministic stream and CLI wiring."""

import gzip
import json
from dataclasses import replace

from argus.config import CONFIG
from argus.contracts import parse_scenario_line
from argus.scenario.generate import generate
from argus.scenario.profiles import build_profile

SCORED_FROM_TS = 1789430400.0


def _tiny_config():
    return replace(
        CONFIG.scenario,
        warmup_hours=0,
        scenario_hours=1,
        resolution_s=60,
    )


def test_canonical_profile_shapes_include_required_win_scenarios():
    match = build_profile("match_night", SCORED_FROM_TS)
    cascade = build_profile("cascade_night", SCORED_FROM_TS)
    combo = build_profile("combo_night", SCORED_FROM_TS)
    quiet = build_profile("quiet_day", SCORED_FROM_TS)

    assert quiet.incidents == ()
    assert match.events[0].ramp_start_ts < match.attacks[0].start_ts
    assert match.attacks[0].end_ts < match.events[0].end_ts
    assert cascade.code_faults[0].fault_id == "F1"
    assert combo.events and combo.attacks and combo.code_faults and combo.operational_faults


def test_generate_is_byte_deterministic_and_contract_parseable(tmp_path):
    config = _tiny_config()
    first = generate(
        seed=77,
        profile="quiet_day",
        output_dir=tmp_path / "first",
        config=config,
    )
    second = generate(
        seed=77,
        profile="quiet_day",
        output_dir=tmp_path / "second",
        config=config,
    )

    assert first.scenario_path.read_bytes() == second.scenario_path.read_bytes()
    assert first.labels_path.read_bytes() == second.labels_path.read_bytes()
    assert first.step_labels_path.read_bytes() == second.step_labels_path.read_bytes()

    with gzip.open(first.scenario_path, "rt", encoding="utf-8") as stream:
        lines = [next(stream) for _ in range(12)]
    parsed = [parse_scenario_line(line) for line in lines]
    assert parsed[0].kind == "header"
    assert {record.kind for record in parsed[1:]} == {"metric", "net"}


def test_match_profile_labels_attack_inside_event(tmp_path):
    config = replace(
        CONFIG.scenario,
        warmup_hours=0,
        scenario_hours=24,
        resolution_s=3600,
    )
    artifacts = generate(
        seed=91,
        profile="match_night",
        output_dir=tmp_path,
        config=config,
    )
    labels = json.loads(artifacts.labels_path.read_text())
    attack = next(item for item in labels["incidents"] if item["class"] == "attack")

    assert attack["inside_event"] == "match-final"
    assert attack["correct_decision"] == "act"
    assert attack["reason_category"] == "behavioral_deformation"
