"""Canonical deterministic scenario compositions."""

from __future__ import annotations

from dataclasses import dataclass

from argus.contracts import (
    CodeFaultLabel,
    DecisionKind,
    GroundTruthIncident,
    IncidentClass,
    ReasonCategory,
)
from argus.scenario.attacks import AttackSpec, AttackType
from argus.scenario.base import SECONDS_PER_HOUR
from argus.scenario.events import EventSpec
from argus.scenario.faults import (
    FaultSpec,
    OperationalFaultSpec,
    OperationalFaultType,
    load_fault_catalog,
)
from argus.scenario.labels import StepLabelSpan


@dataclass(frozen=True)
class ProfilePlan:
    """All visible and hidden inputs composing one scenario profile."""

    name: str
    events: tuple[EventSpec, ...] = ()
    attacks: tuple[AttackSpec, ...] = ()
    code_faults: tuple[FaultSpec, ...] = ()
    operational_faults: tuple[OperationalFaultSpec, ...] = ()
    incidents: tuple[GroundTruthIncident, ...] = ()
    step_spans: tuple[StepLabelSpan, ...] = ()


def _at(scored_from_ts: float, hour: float) -> float:
    return scored_from_ts + hour * SECONDS_PER_HOUR


def _match_event(scored_from_ts: float) -> EventSpec:
    return EventSpec(
        event_id="match-final",
        title="Cup Final",
        announce_ts=_at(scored_from_ts, 12.0),
        ramp_start_ts=_at(scored_from_ts, 17.0),
        peak_start_ts=_at(scored_from_ts, 18.0),
        peak_end_ts=_at(scored_from_ts, 22.0),
        end_ts=_at(scored_from_ts, 23.0),
        multiplier=6.0,
        affects=("edge-gw", "auth-svc", "catalog-svc"),
    )


def quiet_day(scored_from_ts: float) -> ProfilePlan:
    return ProfilePlan(name="quiet_day")


def match_night(scored_from_ts: float) -> ProfilePlan:
    event = _match_event(scored_from_ts)
    attack = AttackSpec(
        attack_id="attack-match",
        attack_type=AttackType.APP_LAYER_FLOOD,
        start_ts=_at(scored_from_ts, 19.0),
        end_ts=_at(scored_from_ts, 20.0),
        target_service="auth-svc",
        cohort="scripted-login-clients",
        intensity=0.9,
        rps_multiplier=2.8,
    )
    return ProfilePlan(
        name="match_night",
        events=(event,),
        attacks=(attack,),
        incidents=(
            GroundTruthIncident(
                gt_id="gt-match-surge",
                incident_class=IncidentClass.EXPECTED_SURGE,
                sub_type="match_event",
                window=(event.ramp_start_ts, event.end_ts),
                origin_service="edge-gw",
                inside_event=event.event_id,
                correct_decision=DecisionKind.SUPPRESS,
                reason_category=ReasonCategory.ENVELOPE_EXPLAINED,
                code_fault=None,
            ),
            GroundTruthIncident(
                gt_id="gt-match-attack",
                incident_class=IncidentClass.ATTACK,
                sub_type=attack.attack_type,
                window=(attack.start_ts, attack.end_ts),
                origin_service=attack.target_service,
                inside_event=event.event_id,
                correct_decision=DecisionKind.ACT,
                reason_category=ReasonCategory.BEHAVIORAL_DEFORMATION,
                code_fault=None,
            ),
        ),
        step_spans=(
            StepLabelSpan(
                gt_id="gt-match-surge",
                start_ts=event.ramp_start_ts,
                end_ts=event.end_ts,
                explained_fraction=1.0,
            ),
            StepLabelSpan(
                gt_id="gt-match-attack",
                start_ts=attack.start_ts,
                end_ts=attack.end_ts,
                attack_fraction=0.45,
            ),
        ),
    )


def cascade_night(scored_from_ts: float) -> ProfilePlan:
    catalog = load_fault_catalog()
    entry = catalog["F1"]
    fault = FaultSpec(
        fault_id="F1",
        deploy_ts=_at(scored_from_ts, 17.5),
        onset_ts=_at(scored_from_ts, 18.0),
        end_ts=_at(scored_from_ts, 19.5),
        severity=0.95,
    )
    return ProfilePlan(
        name="cascade_night",
        code_faults=(fault,),
        incidents=(
            GroundTruthIncident(
                gt_id="gt-retry-storm",
                incident_class=IncidentClass.CODE_FAULT,
                sub_type=entry.sub_type,
                window=(fault.onset_ts, fault.end_ts),
                origin_service=entry.service,
                inside_event=None,
                correct_decision=DecisionKind.ACT,
                reason_category=ReasonCategory.DEPLOY_CORRELATED_CASCADE,
                code_fault=CodeFaultLabel(
                    commit=entry.commit,
                    file=entry.file,
                    line=entry.line,
                    mechanism=entry.mechanism,
                ),
            ),
        ),
        step_spans=(
            StepLabelSpan(
                gt_id="gt-retry-storm",
                start_ts=fault.onset_ts,
                end_ts=fault.end_ts,
                fault_fraction=0.8,
            ),
        ),
    )


def combo_night(scored_from_ts: float) -> ProfilePlan:
    match = match_night(scored_from_ts)
    cascade = cascade_night(scored_from_ts)
    capacity_loss = OperationalFaultSpec(
        fault_id="ops-capacity",
        fault_type=OperationalFaultType.CAPACITY_LOSS,
        onset_ts=_at(scored_from_ts, 20.5),
        end_ts=_at(scored_from_ts, 21.25),
        severity=0.7,
        service="catalog-svc",
    )
    ops_incident = GroundTruthIncident(
        gt_id="gt-capacity-loss",
        incident_class=IncidentClass.OPERATIONAL_FAULT,
        sub_type=capacity_loss.fault_type,
        window=(capacity_loss.onset_ts, capacity_loss.end_ts),
        origin_service=capacity_loss.service or "catalog-svc",
        inside_event=match.events[0].event_id,
        correct_decision=DecisionKind.ACT,
        reason_category=ReasonCategory.SATURATION_NO_DEPLOY,
        code_fault=None,
    )
    return ProfilePlan(
        name="combo_night",
        events=match.events,
        attacks=match.attacks,
        code_faults=cascade.code_faults,
        operational_faults=(capacity_loss,),
        incidents=match.incidents + cascade.incidents + (ops_incident,),
        step_spans=match.step_spans
        + cascade.step_spans
        + (
            StepLabelSpan(
                gt_id=ops_incident.gt_id,
                start_ts=capacity_loss.onset_ts,
                end_ts=capacity_loss.end_ts,
                fault_fraction=0.6,
            ),
        ),
    )


PROFILE_BUILDERS = {
    "quiet_day": quiet_day,
    "match_night": match_night,
    "cascade_night": cascade_night,
    "combo_night": combo_night,
}


def build_profile(name: str, scored_from_ts: float) -> ProfilePlan:
    try:
        builder = PROFILE_BUILDERS[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown profile {name!r}; choose from {', '.join(PROFILE_BUILDERS)}"
        ) from exc
    return builder(scored_from_ts)
