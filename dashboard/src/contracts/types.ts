/* Generated from schema.json (python -m argus.contracts export) — do not edit. */

/**
 * Per-service metric signals every scenario emits at each tick.
 */
export type MetricName =
  "rps" | "err_rate" | "p50_ms" | "p95_ms" | "p99_ms" | "cpu_pct" | "mem_pct" | "conn_active" | "queue_depth";
export type CalendarPhase = "announce" | "ramp" | "start" | "peak" | "end";
/**
 * Ground-truth incident class: verdict classes plus the combination marker.
 *
 * ``expected_surge`` entries exist so suppress decisions are scorable
 * against a labeled window.
 */
export type IncidentClass = "expected_surge" | "attack" | "operational_fault" | "code_fault" | "combination";
export type DecisionKind = "suppress" | "alert" | "act";
/**
 * Scored against verdict evidence themes (right action, right reason).
 */
export type ReasonCategory =
  | "behavioral_deformation"
  | "envelope_explained"
  | "deploy_correlated_cascade"
  | "saturation_no_deploy"
  | "combination_split";
export type IncidentStatus = "open" | "updated" | "resolved";
export type SymptomKind =
  "residual_exceed" | "ratio_deform" | "log_burst" | "edge_degraded" | "saturation" | "deploy_marker";
/**
 * The four base classes a verdict distributes probability over.
 *
 * A combined attack+fault situation is expressed by splitting incidents and
 * setting ``Verdict.combination``, not by a fifth class.
 */
export type VerdictClass = "expected_surge" | "attack" | "operational_fault" | "code_fault";
export type Direction = "up" | "down";
/**
 * RCA cause classes; expected surges never reach RCA.
 */
export type CauseClass = "attack" | "operational_fault" | "code_fault" | "combination";
export type CureKind = "code_fix" | "infra_action";
export type ActionRung =
  "observe" | "rate_limit" | "throttle" | "isolate" | "scale_out" | "pre_scale" | "restart" | "reroute";
/**
 * What an action selector addresses: a traffic cohort (rate_limit /
 * throttle / isolate), a service (scale / restart) or a call edge (reroute).
 */
export type TargetKind = "cohort" | "service" | "edge";
export type RollbackTrigger = "auto" | "human";
export type ClockState = "playing" | "paused" | "ended" | "loading";

export interface ArgusContracts {
  scenario_header?: ScenarioHeader;
  metric_record?: MetricRecord;
  net_record?: NetRecord;
  log_record?: LogRecord;
  trace_record?: TraceRecord;
  calendar_record?: CalendarRecord;
  deploy_record?: DeployRecord;
  ground_truth_labels?: GroundTruthLabels;
  decomp_frame?: DecompFrame;
  incident?: Incident;
  verdict?: Verdict;
  rca_result?: RcaResult;
  decision?: Decision;
  action?: Action;
  rollback?: Rollback;
  clock_payload?: ClockPayload;
  approval_request?: ApprovalRequestPayload;
  mttr_record?: MttrRecord;
  ws_envelope?: WsEnvelope;
}
/**
 * First line of a scenario file: everything the replayer needs to run it.
 */
export interface ScenarioHeader {
  kind: "header";
  contract: string;
  seed: number;
  profile: string;
  start_ts: number;
  scored_from_ts: number;
  end_ts: number;
  resolution_s: number;
  warmup_resolution_s: number;
  /**
   * @minItems 1
   */
  services: [string, ...string[]];
  demo_app_manifest: string;
}
export interface MetricRecord {
  kind: "metric";
  ts: number;
  service: string;
  name: MetricName;
  value: number;
}
/**
 * Load-invariant network behavior features — the volume-vs-behavior axis.
 */
export interface NetRecord {
  kind: "net";
  ts: number;
  service: string;
  uniq_ip_entropy: number;
  syn_ack_ratio: number;
  auth_fail_ratio: number;
  ja3_novelty: number;
  geo_top1_share: number;
}
export interface LogRecord {
  kind: "log";
  ts: number;
  service: string;
  level: string;
  template_id: string;
  msg: string;
  count: number;
}
/**
 * Aggregated caller→callee edge health for one tick.
 */
export interface TraceRecord {
  kind: "trace";
  ts: number;
  caller: string;
  callee: string;
  rps: number;
  err_rate: number;
  p99_ms: number;
}
export interface CalendarRecord {
  kind: "calendar";
  ts: number;
  event_id: string;
  title: string;
  phase: CalendarPhase;
  expected_multiplier: number;
  /**
   * @minItems 1
   */
  affects: [string, ...string[]];
}
export interface DeployRecord {
  kind: "deploy";
  ts: number;
  service: string;
  commit: string;
  author: string;
  /**
   * @minItems 1
   */
  files: [string, ...string[]];
  summary: string;
}
/**
 * Scoring-side ground truth; the argus runtime must never read this
 * (labels-isolation lint, invariant I7).
 */
export interface GroundTruthLabels {
  contract: string;
  seed: number;
  incidents: GroundTruthIncident[];
  timestep_labels_file: string;
}
export interface GroundTruthIncident {
  gt_id: string;
  class: IncidentClass;
  sub_type: string;
  /**
   * @minItems 2
   * @maxItems 2
   */
  window: [unknown, unknown];
  origin_service: string;
  inside_event: string | null;
  correct_decision: DecisionKind;
  reason_category: ReasonCategory;
  code_fault: CodeFaultLabel | null;
}
export interface CodeFaultLabel {
  commit: string;
  file: string;
  line: number;
  mechanism: string;
}
/**
 * Observed volume split into base + event + residual vs the expected band.
 */
export interface DecompFrame {
  type: "decomp";
  ts: number;
  service: string;
  signal: MetricName;
  observed: number;
  explained_base: number;
  explained_event: number;
  residual: number;
  /**
   * @minItems 2
   * @maxItems 2
   */
  band: [unknown, unknown];
  residual_score: number;
}
export interface Incident {
  type: "incident";
  incident_id: string;
  status: IncidentStatus;
  first_ts: number;
  last_ts: number;
  /**
   * @minItems 1
   */
  symptoms: [Symptom, ...Symptom[]];
}
export interface Symptom {
  service: string;
  signal: string;
  kind: SymptomKind;
  onset_ts: number;
  score: number;
}
export interface Verdict {
  type: "verdict";
  incident_id: string;
  /**
   * @minItems 1
   */
  classes: [ClassProbability, ...ClassProbability[]];
  combination: boolean;
  confidence: number;
  /**
   * @minItems 1
   */
  evidence: [EvidenceItem, ...EvidenceItem[]];
}
export interface ClassProbability {
  class: VerdictClass;
  p: number;
}
/**
 * One scored reason line: a feature, where it sits vs baseline, and why
 * that matters for the verdict.
 */
export interface EvidenceItem {
  feature: string;
  value: number;
  baseline: number;
  direction: Direction;
  note: string;
}
export interface RcaResult {
  type: "rca";
  incident_id: string;
  origin: RcaOrigin;
  cause_class: CauseClass;
  /**
   * @minItems 1
   */
  collapse_trace: [string, ...string[]];
  code_fault: CodeFaultFinding | null;
  cure: Cure;
  confidence: number;
}
/**
 * Exactly one origin; alternates are ranked, never co-equal (invariant I8).
 */
export interface RcaOrigin {
  service: string;
  onset_ts: number;
  alternates: AlternateOrigin[];
}
export interface AlternateOrigin {
  service: string;
  score: number;
}
export interface CodeFaultFinding {
  commit: string;
  file: string;
  line: number;
  function: string;
  config_value: string | null;
  mechanism: string;
  proposed_fix: ProposedFix | null;
}
export interface ProposedFix {
  summary: string;
  diff: string;
}
export interface Cure {
  kind: CureKind;
  justification: string;
  interim_infra_action: string | null;
}
export interface Decision {
  type: "decision";
  decision_id: string;
  incident_id: string;
  ts: number;
  decision: DecisionKind;
  reason: string;
  evidence_ref: string;
  confidence: number;
  human_gate: HumanGate;
}
export interface HumanGate {
  required: boolean;
  approved_by: string | null;
  approved_ts: number | null;
}
export interface Action {
  type: "action";
  action_id: string;
  decision_id: string;
  ts: number;
  rung: ActionRung;
  target: ActionTarget;
  blast_radius: BlastRadius;
  trigger: string;
  expected_effect: string;
}
export interface ActionTarget {
  kind: TargetKind;
  selector: string;
  est_traffic_pct: number;
}
export interface BlastRadius {
  protected_cohorts_touched: number;
  max_pct_allowed: number;
  gates_passed: string[];
}
export interface Rollback {
  type: "rollback";
  rollback_id: string;
  action_id: string;
  ts: number;
  trigger: RollbackTrigger;
  cause: string;
  reverted: boolean;
  verification: RollbackVerification;
}
/**
 * Restoration proof: which signals were checked and when.
 */
export interface RollbackVerification {
  users_restored: boolean;
  /**
   * @minItems 1
   */
  checked_signals: [string, ...string[]];
  verified_ts: number;
}
export interface ClockPayload {
  type: "clock";
  speed: 1 | 10 | 60;
  state: ClockState;
  sim_ts: number;
}
export interface ApprovalRequestPayload {
  type: "approval_request";
  decision_id: string;
  proposed_action: Action;
  timeout_s: number;
}
/**
 * The hours→seconds claim, per incident, with the timestamps that prove it.
 */
export interface MttrRecord {
  type: "mttr";
  incident_id: string;
  onset_ts: number;
  detected_ts: number;
  root_caused_ts: number;
  mitigated_ts: number;
  verified_ts: number;
  manual_baseline_s: number;
  autonomous_s: number;
}
/**
 * Every stream message: ordered seq (since_seq catch-up) + dual clocks.
 */
export interface WsEnvelope {
  seq: number;
  wall_ts: number;
  sim_ts: number;
  payload:
    | (
        | DecompFrame
        | Incident
        | Verdict
        | RcaResult
        | Decision
        | Action
        | Rollback
        | MttrRecord
        | ClockPayload
        | ApprovalRequestPayload
      )
    | (MetricRecord | NetRecord | LogRecord | TraceRecord | CalendarRecord | DeployRecord);
}
