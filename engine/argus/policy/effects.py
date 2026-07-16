"""Deterministic action effects applied only to the selected contribution."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from argus.config import CONFIG, PolicyConfig
from argus.contracts import Action, ActionRung


@dataclass(frozen=True)
class ActionEffect:
    before: np.ndarray
    after: np.ndarray
    removed: np.ndarray
    intended_effect_met: bool


def apply_action_effect(
    contribution: np.ndarray,
    action: Action,
    *,
    start_index: int,
    config: PolicyConfig = CONFIG.policy,
) -> ActionEffect:
    """Reduce only the targeted attack contribution after an action fires."""
    before = np.asarray(contribution, dtype=np.float64)
    if not 0 <= start_index <= len(before):
        raise ValueError("start_index must fall inside the contribution array")
    efficacy = {
        ActionRung.RATE_LIMIT: config.rate_limit_efficacy,
        ActionRung.THROTTLE: config.throttle_efficacy,
        ActionRung.ISOLATE: config.isolate_efficacy,
    }.get(action.rung, 0.0)
    after = before.copy()
    after[start_index:] *= 1.0 - efficacy
    removed = before - after
    active_before = float(np.sum(before[start_index:]))
    active_after = float(np.sum(after[start_index:]))
    return ActionEffect(
        before=before,
        after=after,
        removed=removed,
        intended_effect_met=active_before == 0.0 or active_after < active_before,
    )
