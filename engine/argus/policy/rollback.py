"""Automatic rollback record with explicit user-restoration proof."""

from __future__ import annotations

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
