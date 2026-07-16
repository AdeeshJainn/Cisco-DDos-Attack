"""Cluster symptom storms into deterministic incident lifecycles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from argus.config import CONFIG, RcaConfig
from argus.contracts import Incident, IncidentStatus, Symptom, SymptomKind
from argus.scenario.base import DEFAULT_TOPOLOGY_PATH

SymptomKey = tuple[str, str, SymptomKind]


def topology_graph(
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
) -> dict[str, set[str]]:
    with topology_path.open(encoding="utf-8") as handle:
        topology = yaml.safe_load(handle)
    graph = {service: set() for service in topology["services"]}
    for edge in topology["edges"]:
        caller = edge["caller"]
        callee = edge["callee"]
        graph[caller].add(callee)
        graph[callee].add(caller)
    return graph


def within_hops(
    graph: dict[str, set[str]],
    left: str,
    right: str,
    max_hops: int,
) -> bool:
    if left == right:
        return True
    frontier = {left}
    seen = {left}
    for _ in range(max_hops):
        frontier = {
            neighbor
            for service in frontier
            for neighbor in graph.get(service, ())
            if neighbor not in seen
        }
        if right in frontier:
            return True
        seen.update(frontier)
    return False


@dataclass
class _IncidentState:
    incident: Incident
    active: set[SymptomKey] = field(default_factory=set)
    quiet_since: float | None = None


class IncidentBuilder:
    """Stateful time-gap plus topology-adjacency incident builder."""

    def __init__(
        self,
        *,
        topology_path: Path = DEFAULT_TOPOLOGY_PATH,
        config: RcaConfig = CONFIG.rca,
    ) -> None:
        self.config = config
        self.graph = topology_graph(topology_path)
        self._states: list[_IncidentState] = []
        self._next_id = 1

    @property
    def incidents(self) -> tuple[Incident, ...]:
        return tuple(state.incident for state in self._states)

    def ingest(self, symptom: Symptom) -> Incident:
        state = self._matching_state(symptom)
        key = (symptom.service, symptom.signal, symptom.kind)
        if state is None:
            incident = Incident(
                incident_id=f"inc-{self._next_id:04d}",
                status=IncidentStatus.OPEN,
                first_ts=symptom.onset_ts,
                last_ts=symptom.onset_ts,
                symptoms=[symptom],
            )
            self._next_id += 1
            state = _IncidentState(incident=incident)
            self._states.append(state)
        else:
            state.incident = state.incident.model_copy(
                update={
                    "status": IncidentStatus.UPDATED,
                    "first_ts": min(state.incident.first_ts, symptom.onset_ts),
                    "last_ts": max(state.incident.last_ts, symptom.onset_ts),
                    "symptoms": [*state.incident.symptoms, symptom],
                }
            )
        state.active.add(key)
        state.quiet_since = None
        return state.incident

    def release(
        self,
        *,
        service: str,
        signal: str,
        kind: SymptomKind,
        ts: float,
    ) -> Incident | None:
        key = (service, signal, kind)
        for state in self._states:
            if key not in state.active:
                continue
            state.active.remove(key)
            state.incident = state.incident.model_copy(
                update={"last_ts": max(state.incident.last_ts, ts)}
            )
            if not state.active:
                state.quiet_since = ts
            return state.incident
        return None

    def advance(self, ts: float) -> list[Incident]:
        resolved = []
        for state in self._states:
            if (
                state.incident.status is not IncidentStatus.RESOLVED
                and state.quiet_since is not None
                and ts - state.quiet_since >= self.config.resolve_dwell_s
            ):
                state.incident = state.incident.model_copy(
                    update={
                        "status": IncidentStatus.RESOLVED,
                        "last_ts": max(state.incident.last_ts, ts),
                    }
                )
                resolved.append(state.incident)
        return resolved

    def _matching_state(self, symptom: Symptom) -> _IncidentState | None:
        candidates = []
        for state in self._states:
            if state.incident.status is IncidentStatus.RESOLVED:
                continue
            if symptom.onset_ts - state.incident.last_ts > self.config.incident_gap_s:
                continue
            services = {item.service for item in state.incident.symptoms}
            if any(
                within_hops(
                    self.graph,
                    symptom.service,
                    service,
                    self.config.topology_hops,
                )
                for service in services
            ):
                candidates.append(state)
        return min(
            candidates,
            key=lambda item: (item.incident.first_ts, item.incident.incident_id),
            default=None,
        )
