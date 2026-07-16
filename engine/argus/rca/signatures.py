"""Data-derived fault signatures plus generic attack and operations patterns."""

from __future__ import annotations

from dataclasses import dataclass

from argus.contracts import CauseClass, SymptomKind
from argus.scenario.faults import FaultCatalogEntry, load_fault_catalog


@dataclass(frozen=True)
class Signature:
    name: str
    cause_class: CauseClass
    required_kinds: frozenset[SymptomKind]
    evidence: str
    fault: FaultCatalogEntry | None = None


def fault_signatures() -> dict[str, Signature]:
    return {
        fault_id: Signature(
            name=entry.sub_type,
            cause_class=CauseClass.CODE_FAULT,
            required_kinds=frozenset(
                {
                    SymptomKind.DEPLOY_MARKER,
                    SymptomKind.LOG_BURST,
                }
            ),
            evidence=(
                f"deploy {entry.commit[:12]} changed {entry.file}; "
                f"symptoms match {entry.mechanism.replace('_', ' ')}"
            ),
            fault=entry,
        )
        for fault_id, entry in load_fault_catalog().items()
    }


ATTACK_SIGNATURE = Signature(
    name="behavioral_deformation",
    cause_class=CauseClass.ATTACK,
    required_kinds=frozenset({SymptomKind.RATIO_DEFORM}),
    evidence="load-invariant client behavior deformed outside its robust baseline",
)

OPERATIONAL_SIGNATURE = Signature(
    name="internal_degradation_without_deploy",
    cause_class=CauseClass.OPERATIONAL_FAULT,
    required_kinds=frozenset(
        {
            SymptomKind.SATURATION,
            SymptomKind.EDGE_DEGRADED,
        }
    ),
    evidence="internal saturation or dependency degradation has no proximate deploy",
)


def signature_strength(cause_class: CauseClass, kinds: set[SymptomKind]) -> float:
    if cause_class is CauseClass.ATTACK:
        return float(ATTACK_SIGNATURE.required_kinds <= kinds)
    if cause_class is CauseClass.OPERATIONAL_FAULT:
        return float(bool(OPERATIONAL_SIGNATURE.required_kinds & kinds))
    if cause_class is CauseClass.CODE_FAULT:
        return float(
            SymptomKind.DEPLOY_MARKER in kinds
            and bool(
                kinds
                & {
                    SymptomKind.LOG_BURST,
                    SymptomKind.EDGE_DEGRADED,
                    SymptomKind.SATURATION,
                }
            )
        )
    return 0.0
