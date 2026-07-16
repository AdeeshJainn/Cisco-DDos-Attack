"""Pydantic models for every inter-module payload, with JSON-schema export.

Single source of truth for the engine's wire formats: scenario files (JSONL),
ground-truth labels (scoring only — never the runtime), decomposition frames,
incidents, verdicts, RCA results, decisions/actions/rollbacks, the WebSocket
envelope and MTTR records. The dashboard consumes the JSON schema exported
from these models, so any non-additive change here must bump
``argus.CONTRACT_VERSION`` and update every producer and consumer together.

Wire conventions (shared with the dashboard):
- ``ts``/``*_ts`` are epoch seconds (float allowed); durations ``*_s``,
  latencies ``*_ms``, percentages 0-100 ``*_pct``, probabilities/scores 0-1.
- IDs are strings; enums are lowercase snake_case.
- Consumers must ignore unknown fields (forward compatibility) — models keep
  pydantic's default ``extra="ignore"`` on purpose.
- ``class`` is a wire field name (Python keyword), so those fields carry an
  alias; serialization emits wire names by default (``serialize_by_alias``).
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

# --------------------------------------------------------------------------
# Shared validation primitives
# --------------------------------------------------------------------------

# Four class probabilities rounded to two decimals can each drift up to
# 0.005, so a wire-legal distribution may sum anywhere in 1 ± 0.02. This is
# a contract bound (what producers may emit), not a tunable — it does not
# belong in config.py.
PROB_SUM_TOLERANCE = 0.02

# Producers may round the derived autonomous_s to whole seconds while the
# timestamps stay fractional.
DERIVED_SECONDS_TOLERANCE = 1.0


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonBlankStr = Annotated[str, AfterValidator(_non_blank)]
Score = Annotated[float, Field(ge=0.0, le=1.0)]
Pct = Annotated[float, Field(ge=0.0, le=100.0)]


def ensure_ordered(checkpoints: Sequence[tuple[str, float]]) -> None:
    """Raise ValueError unless named timestamps are non-decreasing.

    Shared by model validators (MTTR lifecycle, scenario spans, incident and
    ground-truth windows) and by stream-order tests, so every payload reports
    ordering violations the same way, naming the offending pair.
    """
    for (prev_name, prev_ts), (name, ts) in zip(checkpoints, checkpoints[1:], strict=False):
        if ts < prev_ts:
            raise ValueError(f"{name} ({ts}) precedes {prev_name} ({prev_ts})")


class ContractModel(BaseModel):
    """Base for all payloads: accepts and emits wire names (incl. aliases)."""

    model_config = ConfigDict(
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class MetricName(StrEnum):
    """Per-service metric signals every scenario emits at each tick."""

    RPS = "rps"
    ERR_RATE = "err_rate"
    P50_MS = "p50_ms"
    P95_MS = "p95_ms"
    P99_MS = "p99_ms"
    CPU_PCT = "cpu_pct"
    MEM_PCT = "mem_pct"
    CONN_ACTIVE = "conn_active"
    QUEUE_DEPTH = "queue_depth"


class CalendarPhase(StrEnum):
    ANNOUNCE = "announce"
    RAMP = "ramp"
    START = "start"
    PEAK = "peak"
    END = "end"


class SymptomKind(StrEnum):
    RESIDUAL_EXCEED = "residual_exceed"
    RATIO_DEFORM = "ratio_deform"
    LOG_BURST = "log_burst"
    EDGE_DEGRADED = "edge_degraded"
    SATURATION = "saturation"
    DEPLOY_MARKER = "deploy_marker"


class IncidentStatus(StrEnum):
    OPEN = "open"
    UPDATED = "updated"
    RESOLVED = "resolved"


class VerdictClass(StrEnum):
    """The four base classes a verdict distributes probability over.

    A combined attack+fault situation is expressed by splitting incidents and
    setting ``Verdict.combination``, not by a fifth class.
    """

    EXPECTED_SURGE = "expected_surge"
    ATTACK = "attack"
    OPERATIONAL_FAULT = "operational_fault"
    CODE_FAULT = "code_fault"


class CauseClass(StrEnum):
    """RCA cause classes; expected surges never reach RCA."""

    ATTACK = "attack"
    OPERATIONAL_FAULT = "operational_fault"
    CODE_FAULT = "code_fault"
    COMBINATION = "combination"


class IncidentClass(StrEnum):
    """Ground-truth incident class: verdict classes plus the combination marker.

    ``expected_surge`` entries exist so suppress decisions are scorable
    against a labeled window.
    """

    EXPECTED_SURGE = "expected_surge"
    ATTACK = "attack"
    OPERATIONAL_FAULT = "operational_fault"
    CODE_FAULT = "code_fault"
    COMBINATION = "combination"


class ReasonCategory(StrEnum):
    """Scored against verdict evidence themes (right action, right reason)."""

    BEHAVIORAL_DEFORMATION = "behavioral_deformation"
    ENVELOPE_EXPLAINED = "envelope_explained"
    DEPLOY_CORRELATED_CASCADE = "deploy_correlated_cascade"
    SATURATION_NO_DEPLOY = "saturation_no_deploy"
    COMBINATION_SPLIT = "combination_split"


class DecisionKind(StrEnum):
    SUPPRESS = "suppress"
    ALERT = "alert"
    ACT = "act"


class ActionRung(StrEnum):
    OBSERVE = "observe"
    RATE_LIMIT = "rate_limit"
    THROTTLE = "throttle"
    ISOLATE = "isolate"
    SCALE_OUT = "scale_out"
    PRE_SCALE = "pre_scale"
    RESTART = "restart"
    REROUTE = "reroute"


class TargetKind(StrEnum):
    """What an action selector addresses: a traffic cohort (rate_limit /
    throttle / isolate), a service (scale / restart) or a call edge (reroute)."""

    COHORT = "cohort"
    SERVICE = "service"
    EDGE = "edge"


class RollbackTrigger(StrEnum):
    AUTO = "auto"
    HUMAN = "human"


class CureKind(StrEnum):
    CODE_FIX = "code_fix"
    INFRA_ACTION = "infra_action"


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"


class ClockState(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    ENDED = "ended"
    LOADING = "loading"


# --------------------------------------------------------------------------
# §1 Scenario file (scenario engine → replay)
# --------------------------------------------------------------------------


class ScenarioHeader(ContractModel):
    """First line of a scenario file: everything the replayer needs to run it."""

    kind: Literal["header"] = "header"
    contract: NonBlankStr
    seed: int
    profile: NonBlankStr
    start_ts: float
    # Warmup (coarser resolution) precedes this; scoring and goldens start here.
    scored_from_ts: float
    end_ts: float
    resolution_s: float = Field(gt=0)
    warmup_resolution_s: float = Field(gt=0)
    services: list[NonBlankStr] = Field(min_length=1)
    # Deploy-record commit hashes are sourced from this demo-app lockfile.
    demo_app_manifest: NonBlankStr

    @model_validator(mode="after")
    def _spans_ordered(self) -> "ScenarioHeader":
        ensure_ordered(
            [
                ("start_ts", self.start_ts),
                ("scored_from_ts", self.scored_from_ts),
                ("end_ts", self.end_ts),
            ]
        )
        return self


class MetricRecord(ContractModel):
    kind: Literal["metric"] = "metric"
    ts: float
    service: NonBlankStr
    name: MetricName
    value: float


class NetRecord(ContractModel):
    """Load-invariant network behavior features — the volume-vs-behavior axis."""

    kind: Literal["net"] = "net"
    ts: float
    service: NonBlankStr
    uniq_ip_entropy: float = Field(ge=0)
    # SYN:ACK can legitimately exceed 1 (half-open floods push it far above).
    syn_ack_ratio: float = Field(ge=0)
    auth_fail_ratio: Score
    ja3_novelty: Score
    geo_top1_share: Score


class LogRecord(ContractModel):
    kind: Literal["log"] = "log"
    ts: float
    service: NonBlankStr
    # Lowercase level names; the contract does not enumerate them — detection
    # keys on template_id, not level.
    level: NonBlankStr
    template_id: NonBlankStr
    msg: str
    count: int = Field(ge=1)


class TraceRecord(ContractModel):
    """Aggregated caller→callee edge health for one tick."""

    kind: Literal["trace"] = "trace"
    ts: float
    caller: NonBlankStr
    callee: NonBlankStr
    rps: float = Field(ge=0)
    err_rate: Score
    p99_ms: float = Field(ge=0)


class CalendarRecord(ContractModel):
    kind: Literal["calendar"] = "calendar"
    ts: float
    event_id: NonBlankStr
    title: str
    phase: CalendarPhase
    expected_multiplier: float = Field(gt=0)
    affects: list[NonBlankStr] = Field(min_length=1)


class DeployRecord(ContractModel):
    kind: Literal["deploy"] = "deploy"
    ts: float
    service: NonBlankStr
    # A real hash from the materialized demo-app history (manifest lock).
    commit: NonBlankStr
    author: NonBlankStr
    files: list[NonBlankStr] = Field(min_length=1)
    summary: str


TelemetryRecord = Annotated[
    MetricRecord | NetRecord | LogRecord | TraceRecord | CalendarRecord | DeployRecord,
    Field(discriminator="kind"),
]

ScenarioLine = Annotated[
    ScenarioHeader
    | MetricRecord
    | NetRecord
    | LogRecord
    | TraceRecord
    | CalendarRecord
    | DeployRecord,
    Field(discriminator="kind"),
]

SCENARIO_LINE_ADAPTER: TypeAdapter[Any] = TypeAdapter(ScenarioLine)


def parse_scenario_line(raw: str | bytes) -> Any:
    """Parse one JSONL line of a scenario file into its record model."""
    return SCENARIO_LINE_ADAPTER.validate_json(raw)


# --------------------------------------------------------------------------
# §2 Ground-truth labels (scenario engine → scoring ONLY, never the runtime)
# --------------------------------------------------------------------------


class CodeFaultLabel(ContractModel):
    commit: NonBlankStr
    file: NonBlankStr
    line: int = Field(ge=1)
    mechanism: NonBlankStr


class GroundTruthIncident(ContractModel):
    gt_id: NonBlankStr
    incident_class: IncidentClass = Field(alias="class")
    sub_type: NonBlankStr
    window: tuple[float, float]
    origin_service: NonBlankStr
    inside_event: str | None = None
    correct_decision: DecisionKind
    reason_category: ReasonCategory
    code_fault: CodeFaultLabel | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "GroundTruthIncident":
        ensure_ordered([("window[0]", self.window[0]), ("window[1]", self.window[1])])
        if self.incident_class is IncidentClass.CODE_FAULT and self.code_fault is None:
            raise ValueError("class 'code_fault' requires a code_fault label")
        return self


class GroundTruthLabels(ContractModel):
    """Scoring-side ground truth; the argus runtime must never read this
    (labels-isolation lint, invariant I7)."""

    contract: NonBlankStr
    seed: int
    # Quiet profiles legitimately have zero incidents.
    incidents: list[GroundTruthIncident] = Field(default_factory=list)
    timestep_labels_file: NonBlankStr


# --------------------------------------------------------------------------
# §3 Decomposition frame (detection → dashboard/RCA/scoring)
# --------------------------------------------------------------------------


class DecompFrame(ContractModel):
    """Observed volume split into base + event + residual vs the expected band."""

    type: Literal["decomp"] = "decomp"
    ts: float
    service: NonBlankStr
    signal: MetricName
    observed: float
    explained_base: float
    explained_event: float
    residual: float
    # Expected [low, high] for this tick.
    band: tuple[float, float]
    residual_score: Score

    @model_validator(mode="after")
    def _band_ordered(self) -> "DecompFrame":
        ensure_ordered([("band[0]", self.band[0]), ("band[1]", self.band[1])])
        return self


# --------------------------------------------------------------------------
# §4 Incident (incident builder → verdict/policy/dashboard)
# --------------------------------------------------------------------------


class Symptom(ContractModel):
    service: NonBlankStr
    # Metric or net-feature name — deliberately wider than MetricName.
    signal: NonBlankStr
    kind: SymptomKind
    onset_ts: float
    score: Score


class Incident(ContractModel):
    type: Literal["incident"] = "incident"
    incident_id: NonBlankStr
    status: IncidentStatus
    first_ts: float
    last_ts: float
    # An incident with no symptom evidence is unfounded (invariant I2).
    symptoms: list[Symptom] = Field(min_length=1)

    @model_validator(mode="after")
    def _window_ordered(self) -> "Incident":
        ensure_ordered([("first_ts", self.first_ts), ("last_ts", self.last_ts)])
        return self


# --------------------------------------------------------------------------
# §5 Verdict (verdict → policy/dashboard)
# --------------------------------------------------------------------------


class ClassProbability(ContractModel):
    verdict_class: VerdictClass = Field(alias="class")
    p: Score


class EvidenceItem(ContractModel):
    """One scored reason line: a feature, where it sits vs baseline, and why
    that matters for the verdict."""

    feature: NonBlankStr
    value: float
    baseline: float
    direction: Direction
    note: NonBlankStr


class Verdict(ContractModel):
    type: Literal["verdict"] = "verdict"
    incident_id: NonBlankStr
    classes: list[ClassProbability] = Field(min_length=1)
    combination: bool = False
    confidence: Score
    # The scored "reason" — a verdict without evidence is a build error.
    evidence: list[EvidenceItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _distribution_valid(self) -> "Verdict":
        names = [c.verdict_class for c in self.classes]
        if len(set(names)) != len(names):
            raise ValueError("classes must not repeat a verdict class")
        total = sum(c.p for c in self.classes)
        if abs(total - 1.0) > PROB_SUM_TOLERANCE:
            raise ValueError(f"class probabilities sum to {total:.4f}, expected ≈ 1")
        return self


# --------------------------------------------------------------------------
# §6 RCA result (RCA → policy/reports/dashboard)
# --------------------------------------------------------------------------


class AlternateOrigin(ContractModel):
    service: NonBlankStr
    score: Score


class RcaOrigin(ContractModel):
    """Exactly one origin; alternates are ranked, never co-equal (invariant I8)."""

    service: NonBlankStr
    onset_ts: float
    alternates: list[AlternateOrigin] = Field(default_factory=list)


class ProposedFix(ContractModel):
    summary: NonBlankStr
    # Unified diff against the demo-app tree.
    diff: NonBlankStr


class CodeFaultFinding(ContractModel):
    commit: NonBlankStr
    file: NonBlankStr
    line: int = Field(ge=1)
    function: NonBlankStr
    # Present when the offending diff changes a constant.
    config_value: str | None = None
    mechanism: NonBlankStr
    # Filled asynchronously (LLM or offline template); reports require it,
    # first emission may precede it.
    proposed_fix: ProposedFix | None = None


class Cure(ContractModel):
    kind: CureKind
    # Scored alongside the recommendation itself — never blank.
    justification: NonBlankStr
    interim_infra_action: str | None = None


class RcaResult(ContractModel):
    type: Literal["rca"] = "rca"
    incident_id: NonBlankStr
    origin: RcaOrigin
    cause_class: CauseClass
    # Human-readable evidence chain, one step per line.
    collapse_trace: list[NonBlankStr] = Field(min_length=1)
    code_fault: CodeFaultFinding | None = None
    cure: Cure
    confidence: Score

    @model_validator(mode="after")
    def _code_fault_localized(self) -> "RcaResult":
        if self.cause_class is CauseClass.CODE_FAULT and self.code_fault is None:
            raise ValueError("cause_class 'code_fault' requires a code_fault finding")
        return self


# --------------------------------------------------------------------------
# §7 Decision / action / rollback (policy → audit/dashboard/effects)
# --------------------------------------------------------------------------


class HumanGate(ContractModel):
    required: bool
    approved_by: str | None = None
    approved_ts: float | None = None

    @model_validator(mode="after")
    def _approval_complete(self) -> "HumanGate":
        if (self.approved_by is None) != (self.approved_ts is None):
            raise ValueError("approved_by and approved_ts must be set together")
        return self


class Decision(ContractModel):
    type: Literal["decision"] = "decision"
    decision_id: NonBlankStr
    incident_id: NonBlankStr
    ts: float
    decision: DecisionKind
    # Scored verbatim next to the decision — never blank (invariant I5).
    reason: NonBlankStr
    evidence_ref: NonBlankStr
    confidence: Score
    human_gate: HumanGate


class ActionTarget(ContractModel):
    kind: TargetKind
    selector: NonBlankStr
    est_traffic_pct: Pct


class BlastRadius(ContractModel):
    # Guards hold this at zero (invariant I4); the field records what
    # happened rather than assuming it.
    protected_cohorts_touched: int = Field(ge=0)
    max_pct_allowed: Pct
    gates_passed: list[NonBlankStr] = Field(default_factory=list)


class Action(ContractModel):
    type: Literal["action"] = "action"
    action_id: NonBlankStr
    decision_id: NonBlankStr
    ts: float
    rung: ActionRung
    target: ActionTarget
    blast_radius: BlastRadius
    trigger: NonBlankStr
    expected_effect: NonBlankStr


class RollbackVerification(ContractModel):
    """Restoration proof: which signals were checked and when."""

    users_restored: bool
    checked_signals: list[NonBlankStr] = Field(min_length=1)
    verified_ts: float


class Rollback(ContractModel):
    type: Literal["rollback"] = "rollback"
    rollback_id: NonBlankStr
    action_id: NonBlankStr
    ts: float
    trigger: RollbackTrigger
    cause: NonBlankStr
    reverted: bool
    # Mandatory: every rollback carries its verification record (invariant I5).
    verification: RollbackVerification


# --------------------------------------------------------------------------
# §9 MTTR record (audit → dashboard/pitch)
# --------------------------------------------------------------------------


class MttrRecord(ContractModel):
    """The hours→seconds claim, per incident, with the timestamps that prove it."""

    type: Literal["mttr"] = "mttr"
    incident_id: NonBlankStr
    onset_ts: float
    detected_ts: float
    root_caused_ts: float
    mitigated_ts: float
    verified_ts: float
    manual_baseline_s: float = Field(gt=0)
    autonomous_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _lifecycle_consistent(self) -> "MttrRecord":
        ensure_ordered(
            [
                ("onset_ts", self.onset_ts),
                ("detected_ts", self.detected_ts),
                ("root_caused_ts", self.root_caused_ts),
                ("mitigated_ts", self.mitigated_ts),
                ("verified_ts", self.verified_ts),
            ]
        )
        # autonomous_s is derived (verified - onset) but kept on the wire for
        # the dashboard banner; it must agree with the timestamps it claims
        # to summarize.
        span = self.verified_ts - self.onset_ts
        if abs(self.autonomous_s - span) > DERIVED_SECONDS_TOLERANCE:
            raise ValueError(
                f"autonomous_s ({self.autonomous_s}) disagrees with verified_ts - onset_ts ({span})"
            )
        return self


# --------------------------------------------------------------------------
# §8 WebSocket stream (engine → dashboard)
# --------------------------------------------------------------------------


class ClockPayload(ContractModel):
    type: Literal["clock"] = "clock"
    speed: Literal[1, 10, 60]
    state: ClockState
    sim_ts: float


class ApprovalRequestPayload(ContractModel):
    type: Literal["approval_request"] = "approval_request"
    decision_id: NonBlankStr
    proposed_action: Action
    timeout_s: float = Field(gt=0)


EnginePayload = Annotated[
    DecompFrame
    | Incident
    | Verdict
    | RcaResult
    | Decision
    | Action
    | Rollback
    | MttrRecord
    | ClockPayload
    | ApprovalRequestPayload,
    Field(discriminator="type"),
]

# Two discriminator axes on purpose: engine payloads carry "type", telemetry
# ticks carry "kind"; pydantic tries the tagged unions left to right.
WsPayload = Union[EnginePayload, TelemetryRecord]  # noqa: UP007 — Annotated unions, `|` invalid

WS_PAYLOAD_ADAPTER: TypeAdapter[Any] = TypeAdapter(WsPayload)


class WsEnvelope(ContractModel):
    """Every stream message: ordered seq (since_seq catch-up) + dual clocks."""

    seq: int = Field(ge=0)
    wall_ts: float
    sim_ts: float
    payload: WsPayload


# --------------------------------------------------------------------------
# Registry — drives the fixture suite and the JSON-schema export
# --------------------------------------------------------------------------

# One entry per contract section (unions covered via their envelope/adapter).
CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "scenario_header": ScenarioHeader,
    "metric_record": MetricRecord,
    "net_record": NetRecord,
    "log_record": LogRecord,
    "trace_record": TraceRecord,
    "calendar_record": CalendarRecord,
    "deploy_record": DeployRecord,
    "ground_truth_labels": GroundTruthLabels,
    "decomp_frame": DecompFrame,
    "incident": Incident,
    "verdict": Verdict,
    "rca_result": RcaResult,
    "decision": Decision,
    "action": Action,
    "rollback": Rollback,
    "clock_payload": ClockPayload,
    "approval_request": ApprovalRequestPayload,
    "mttr_record": MttrRecord,
    "ws_envelope": WsEnvelope,
}
