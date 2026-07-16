"""Human-in-the-loop approval checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ApprovalVerdict(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class Approval:
    decision_id: str
    verdict: ApprovalVerdict
    by: str
    ts: float


class ApprovalStore:
    def __init__(self) -> None:
        self._approvals: dict[str, Approval] = {}

    def resolve(
        self,
        decision_id: str,
        *,
        verdict: ApprovalVerdict,
        by: str,
        ts: float,
    ) -> Approval:
        if decision_id in self._approvals:
            raise ValueError(f"decision {decision_id} already resolved")
        if not by.strip():
            raise ValueError("approver must be populated")
        approval = Approval(
            decision_id=decision_id,
            verdict=verdict,
            by=by.strip(),
            ts=ts,
        )
        self._approvals[decision_id] = approval
        return approval

    def get(self, decision_id: str) -> Approval | None:
        return self._approvals.get(decision_id)
