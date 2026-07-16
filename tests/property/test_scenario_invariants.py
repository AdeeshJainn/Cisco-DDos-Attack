"""P3.8 cross-profile determinism and secret-seed posture."""

import gzip
import json
from dataclasses import replace

import pytest
from argus.config import CONFIG
from argus.contracts import parse_scenario_line
from argus.scenario.generate import generate
from argus.scenario.profiles import PROFILE_BUILDERS, build_profile

SCORED_FROM_TS = 1789430400.0


@pytest.fixture(scope="module")
def coarse_config():
    return replace(
        CONFIG.scenario,
        warmup_hours=1,
        scenario_hours=24,
        warmup_resolution_s=3600,
        resolution_s=3600,
    )


@pytest.mark.parametrize("profile", PROFILE_BUILDERS)
def test_every_profile_is_byte_deterministic(profile, coarse_config, tmp_path):
    first = generate(
        seed=2026,
        profile=profile,
        output_dir=tmp_path / "first",
        config=coarse_config,
    )
    second = generate(
        seed=2026,
        profile=profile,
        output_dir=tmp_path / "second",
        config=coarse_config,
    )

    assert first.scenario_path.read_bytes() == second.scenario_path.read_bytes()
    assert first.labels_path.read_bytes() == second.labels_path.read_bytes()
    assert first.step_labels_path.read_bytes() == second.step_labels_path.read_bytes()
    assert first.scenario_path.read_bytes()[4:8] == b"\x00\x00\x00\x00"


def test_different_seed_changes_stream_without_changing_profile_shape(coarse_config, tmp_path):
    first = generate(
        seed=10,
        profile="match_night",
        output_dir=tmp_path / "first",
        config=coarse_config,
    )
    second = generate(
        seed=11,
        profile="match_night",
        output_dir=tmp_path / "second",
        config=coarse_config,
    )

    assert first.scenario_path.read_bytes() != second.scenario_path.read_bytes()
    first_labels = json.loads(first.labels_path.read_text())
    second_labels = json.loads(second.labels_path.read_text())
    assert first_labels["incidents"] == second_labels["incidents"]


@pytest.mark.parametrize("profile", PROFILE_BUILDERS)
def test_generated_stream_is_time_ordered_and_contract_parseable(
    profile,
    coarse_config,
    tmp_path,
):
    artifacts = generate(
        seed=99,
        profile=profile,
        output_dir=tmp_path,
        config=coarse_config,
    )
    with gzip.open(artifacts.scenario_path, "rt", encoding="utf-8") as stream:
        header = parse_scenario_line(next(stream))
        records = [parse_scenario_line(line) for line in stream]

    assert header.profile == profile
    assert all(left.ts <= right.ts for left, right in zip(records, records[1:], strict=False))


def test_profile_sanity_matches_win_scenarios_and_quiet_day():
    quiet = build_profile("quiet_day", SCORED_FROM_TS)
    match = build_profile("match_night", SCORED_FROM_TS)
    cascade = build_profile("cascade_night", SCORED_FROM_TS)

    assert quiet.incidents == ()
    event = match.events[0]
    attack = match.attacks[0]
    assert event.ramp_start_ts < attack.start_ts < attack.end_ts < event.end_ts
    assert cascade.code_faults[0].fault_id == "F1"
    assert cascade.incidents[0].code_fault is not None
