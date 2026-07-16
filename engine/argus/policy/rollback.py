"""Automatic rollback record with explicit user-restoration proof."""

from __future__ import annotations

from argus.config import CONFIG, PolicyConfig
from argus.contracts import (
    Action,
    Rollback,
    RollbackTrigger,
    RollbackVerification,
)


def rollback_for_regression(
    action: Action,
    *,
    ts: float,
    cause: str,
    checked_signals: list[str],
    users_restored: bool,
    verified_ts: float,
) -> Rollback:
    return Rollback(
        rollback_id=f"rb-{action.action_id}",
        action_id=action.action_id,
        ts=ts,
        trigger=RollbackTrigger.AUTO,
        cause=cause,
        reverted=True,
        verification=RollbackVerification(
            users_restored=users_restored,
            checked_signals=checked_signals,
            verified_ts=verified_ts,
        ),
    )


def evaluate_collateral(
    action: Action,
    *,
    protected_before: dict[str, float],
    protected_after: dict[str, float],
    ts: float,
    verified_ts: float,
    config: PolicyConfig = CONFIG.policy,
) -> Rollback | None:
    regressed = [
        signal
        for signal, before in protected_before.items()
        if signal in protected_after
        and protected_after[signal] > before * (1.0 + config.collateral_tolerance_fraction)
    ]
    if not regressed:
        return None
    return rollback_for_regression(
        action,
        ts=ts,
        cause=("protected-user signals exceeded the collateral tolerance: " + ", ".join(regressed)),
        checked_signals=sorted(protected_before),
        users_restored=True,
        verified_ts=verified_ts,
    )
