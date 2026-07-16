"""P8.1 report rendering and release-gate tests."""

from dataclasses import replace

from scoring.evaluate import ProfileMetrics, gate_failures, render_markdown


def _metrics(profile: str) -> ProfileMetrics:
    return ProfileMetrics(
        profile=profile,
        cases=2,
        incidents=0 if profile == "quiet_day" else 2,
        decision_accuracy=1.0,
        decision_reason_score=1.0,
        attack_recall=1.0 if profile in {"match_night", "combo_night"} else None,
        origin_accuracy=None if profile == "quiet_day" else 1.0,
        file_line_accuracy=(1.0 if profile in {"cascade_night", "combo_night"} else None),
        quiet_false_acts=0,
        median_detect_latency_s=(8.0 if profile in {"match_night", "combo_night"} else None),
        median_resolution_s=None if profile == "quiet_day" else 91.0,
    )


def test_release_gates_accept_complete_metrics():
    metrics = [
        _metrics(profile)
        for profile in ("quiet_day", "match_night", "cascade_night", "combo_night")
    ]

    assert gate_failures(metrics) == []


def test_release_gates_reject_decision_and_origin_regression():
    metrics = [
        _metrics(profile)
        for profile in ("quiet_day", "match_night", "cascade_night", "combo_night")
    ]
    metrics[-1] = replace(
        metrics[-1],
        decision_accuracy=0.0,
        origin_accuracy=0.5,
    )

    failures = gate_failures(metrics)

    assert any("decision accuracy" in failure for failure in failures)
    assert any("origin accuracy" in failure for failure in failures)


def test_markdown_report_contains_scored_dimensions():
    report = render_markdown([_metrics("match_night")], [9200, 9201])

    assert "Decision+reason" in report
    assert "Attack recall" in report
    assert "Detect p50" in report
