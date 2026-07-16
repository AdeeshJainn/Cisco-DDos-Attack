"""Reviewable golden decision transcripts for the four canonical profiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from argus.config import CONFIG, ScoringConfig
from argus.pipeline import analyze_profile
from argus.scenario.generate import DEFAULT_SCORED_FROM_TS

GOLDEN_VERSION = 1
GOLDEN_DIR = Path(__file__).resolve().parents[1] / "tests" / "golden" / "fixtures"
GOLDEN_CASES = (
    ("quiet_day", 424242),
    ("match_night", 424242),
    ("cascade_night", 424242),
    ("combo_night", 424242),
)


def build_transcript(profile: str, seed: int) -> dict[str, Any]:
    findings = analyze_profile(profile=profile, seed=seed)
    entries = []
    for finding in findings:
        top = max(finding.verdict.classes, key=lambda item: item.p)
        code = finding.rca.code_fault
        entries.append(
            {
                "incident_id": finding.incident.incident_id,
                "onset_offset_s": finding.incident.first_ts - DEFAULT_SCORED_FROM_TS,
                "last_offset_s": finding.incident.last_ts - DEFAULT_SCORED_FROM_TS,
                "verdict_class": top.verdict_class,
                "verdict_confidence": finding.verdict.confidence,
                "origin_service": finding.rca.origin.service,
                "cause_class": finding.rca.cause_class,
                "rca_confidence": finding.rca.confidence,
                "decision": finding.decision.decision,
                "decision_reason": finding.decision.reason,
                "evidence_ref": finding.decision.evidence_ref,
                "action_rung": finding.action.rung if finding.action is not None else None,
                "code_fault": (
                    {
                        "commit": code.commit,
                        "file": code.file,
                        "line": code.line,
                        "mechanism": code.mechanism,
                    }
                    if code is not None
                    else None
                ),
            }
        )
    return {
        "golden_version": GOLDEN_VERSION,
        "profile": profile,
        "seed": seed,
        "transcript": entries,
    }


def compare_transcripts(
    expected: dict[str, Any],
    actual: dict[str, Any],
    config: ScoringConfig = CONFIG.scoring,
) -> list[str]:
    errors = []
    for key in ("golden_version", "profile", "seed"):
        if expected.get(key) != actual.get(key):
            errors.append(f"{key}: expected {expected.get(key)!r}, got {actual.get(key)!r}")
    expected_rows = expected.get("transcript", [])
    actual_rows = actual.get("transcript", [])
    if len(expected_rows) != len(actual_rows):
        errors.append(f"incident count: expected {len(expected_rows)}, got {len(actual_rows)}")
        return errors

    exact_fields = (
        "incident_id",
        "verdict_class",
        "origin_service",
        "cause_class",
        "decision",
        "decision_reason",
        "evidence_ref",
        "action_rung",
        "code_fault",
    )
    time_fields = ("onset_offset_s", "last_offset_s")
    confidence_fields = ("verdict_confidence", "rca_confidence")
    for index, (left, right) in enumerate(zip(expected_rows, actual_rows, strict=True)):
        prefix = f"transcript[{index}]"
        for field in exact_fields:
            if left.get(field) != right.get(field):
                errors.append(
                    f"{prefix}.{field}: expected {left.get(field)!r}, got {right.get(field)!r}"
                )
        for field in time_fields:
            delta = abs(float(left[field]) - float(right[field]))
            if delta > config.golden_time_tolerance_s:
                errors.append(
                    f"{prefix}.{field}: delta {delta:.1f}s exceeds "
                    f"{config.golden_time_tolerance_s:.1f}s"
                )
        for field in confidence_fields:
            delta = abs(float(left[field]) - float(right[field]))
            if delta > config.golden_confidence_tolerance:
                errors.append(
                    f"{prefix}.{field}: delta {delta:.3f} exceeds "
                    f"{config.golden_confidence_tolerance:.3f}"
                )
    return errors


def golden_path(profile: str, seed: int) -> Path:
    return GOLDEN_DIR / f"{profile}-seed-{seed}.json"


def write_goldens() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for profile, seed in GOLDEN_CASES:
        path = golden_path(profile, seed)
        path.write_text(
            json.dumps(build_transcript(profile, seed), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path.relative_to(Path.cwd())}")


def check_goldens() -> list[str]:
    errors = []
    for profile, seed in GOLDEN_CASES:
        path = golden_path(profile, seed)
        if not path.exists():
            errors.append(f"missing golden: {path}")
            continue
        expected = json.loads(path.read_text(encoding="utf-8"))
        actual = build_transcript(profile, seed)
        errors.extend(f"{profile}: {error}" for error in compare_transcripts(expected, actual))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite transcripts; review the git diff before committing",
    )
    args = parser.parse_args()
    if args.write:
        write_goldens()
        return 0
    errors = check_goldens()
    if errors:
        print("\n".join(errors))
        return 1
    print(f"golden replay suite: {len(GOLDEN_CASES)} profiles clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
