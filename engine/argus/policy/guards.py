"""Blast-radius and protected-cohort guards."""

from __future__ import annotations

from argus.config import CONFIG, PolicyConfig


def guard_target(
    selector: str,
    *,
    estimated_pct: float,
    max_pct: float,
    config: PolicyConfig = CONFIG.policy,
) -> list[str]:
    normalized = selector.casefold()
    touched = [cohort for cohort in config.protected_cohorts if cohort.casefold() in normalized]
    if touched:
        raise ValueError(f"selector touches protected cohorts: {', '.join(touched)}")
    if estimated_pct > max_pct:
        raise ValueError(f"estimated blast radius {estimated_pct:.1f}% exceeds {max_pct:.1f}% cap")
    return [
        "protected_untouched",
        f"estimated_traffic_pct<={max_pct:.1f}",
    ]
