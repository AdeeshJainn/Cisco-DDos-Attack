"""P8.2 full-pipeline transcript regression suite."""

import json

import pytest

from scoring.golden import (
    GOLDEN_CASES,
    build_transcript,
    compare_transcripts,
    golden_path,
)


@pytest.mark.parametrize(("profile", "seed"), GOLDEN_CASES)
def test_replay_transcript_matches_reviewed_golden(profile: str, seed: int):
    expected = json.loads(golden_path(profile, seed).read_text(encoding="utf-8"))
    actual = build_transcript(profile, seed)

    assert compare_transcripts(expected, actual) == []


def test_tolerance_allows_small_timing_and_confidence_drift():
    expected = {
        "golden_version": 1,
        "profile": "match_night",
        "seed": 1,
        "transcript": [
            {
                "incident_id": "inc",
                "onset_offset_s": 100.0,
                "last_offset_s": 200.0,
                "verdict_class": "attack",
                "verdict_confidence": 0.8,
                "origin_service": "auth-svc",
                "cause_class": "attack",
                "rca_confidence": 0.7,
                "decision": "act",
                "decision_reason": "behavior deformed",
                "evidence_ref": "inc/verdict",
                "action_rung": "rate_limit",
                "code_fault": None,
            }
        ],
    }
    actual = json.loads(json.dumps(expected))
    actual["transcript"][0]["onset_offset_s"] += 30.0
    actual["transcript"][0]["verdict_confidence"] += 0.1

    assert compare_transcripts(expected, actual) == []


def test_semantic_decision_drift_is_never_tolerated():
    expected = {
        "golden_version": 1,
        "profile": "quiet_day",
        "seed": 1,
        "transcript": [],
    }
    actual = {
        **expected,
        "transcript": [
            {
                "incident_id": "false-act",
            }
        ],
    }

    assert compare_transcripts(expected, actual)
