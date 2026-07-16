import { useEffect, useState } from "react";
import { DecompositionChart } from "./components/hello-chart";
import { ThemeToggle } from "./components/theme-toggle";

interface Evidence {
  note: string;
}

interface IncidentBundle {
  incident: {
    incident_id: string;
    status: string;
    symptoms: Array<{ service: string; kind: string; signal: string }>;
  };
  verdict: {
    classes: Array<{ class: string; p: number }>;
    confidence: number;
    evidence: Evidence[];
  };
  rca: {
    origin: { service: string; alternates: Array<{ service: string; score: number }> };
    cause_class: string;
    collapse_trace: string[];
    confidence: number;
    code_fault: null | {
      commit: string;
      file: string;
      line: number;
      mechanism: string;
      proposed_fix: null | { summary: string; diff: string };
    };
    cure: { justification: string; interim_infra_action: string | null };
  };
  decision: {
    decision_id: string;
    decision: string;
    reason: string;
    confidence: number;
  };
  action: null | {
    rung: string;
    target: { selector: string; est_traffic_pct: number };
    blast_radius: {
      protected_cohorts_touched: number;
      gates_passed: string[];
    };
    expected_effect: string;
  };
  report?: string;
}

interface DemoSnapshot {
  mode: string;
  profile: string;
  seed: number;
  timeline: {
    labels: string[];
    base: number[];
    event: number[];
    residual: number[];
    mitigated_residual: number[];
    observed: number[];
  };
  ratios: Record<string, number[]>;
  topology: {
    services: string[];
    edges: Array<{ caller: string; callee: string }>;
    origin: string;
    attack_target: string;
  };
  mttr: {
    autonomous_s: number;
    manual_baseline_s: number;
  };
  audit: Array<{
    type: string;
    incident_id: string;
    decision?: string;
    reason?: string;
    rung?: string;
  }>;
  incidents: IncidentBundle[];
}

interface AnalyzeFinding {
  rca: {
    cause_class: string;
    origin: { service: string };
    code_fault: null | { file: string; line: number };
  };
  decision: {
    decision: string;
    reason: string;
  };
}

function topClass(bundle: IncidentBundle) {
  return bundle.verdict.classes.reduce((best, item) =>
    item.p > best.p ? item : best,
  );
}

function Chip({ children, tone }: { children: React.ReactNode; tone: string }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.14em] ${tone}`}
    >
      {children}
    </span>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<DemoSnapshot | null>(null);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<1 | 10 | 60>(60);
  const [cursor, setCursor] = useState(0);
  const [approval, setApproval] = useState("");
  const [secretSeed, setSecretSeed] = useState(9001);
  const [seedStatus, setSeedStatus] = useState("");
  const [seedFindings, setSeedFindings] = useState<AnalyzeFinding[]>([]);

  useEffect(() => {
    fetch("/api/demo")
      .then((response) => {
        if (!response.ok) throw new Error(`demo API returned ${response.status}`);
        return response.json() as Promise<DemoSnapshot>;
      })
      .then(setSnapshot)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!snapshot || !playing) return;
    const timer = window.setInterval(() => {
      setCursor((current) => {
        const last = snapshot.timeline.labels.length - 1;
        if (current >= last) {
          setPlaying(false);
          return last;
        }
        return Math.min(last, current + Math.max(1, Math.round(speed / 10)));
      });
    }, 350);
    return () => window.clearInterval(timer);
  }, [playing, snapshot, speed]);

  if (error) {
    return (
      <main className="min-h-screen bg-page p-8 text-ink">
        <h1 className="text-3xl">Argus could not load the replay.</h1>
        <p className="mt-4 text-danger">{error}</p>
      </main>
    );
  }

  if (!snapshot) {
    return (
      <main className="grid min-h-screen place-items-center bg-page text-ink">
        <div className="text-center">
          <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-line border-t-accent" />
          <p className="mt-4 text-sm text-muted">Assembling evidence chain…</p>
        </div>
      </main>
    );
  }

  const attack = snapshot.incidents[0];
  const fault = snapshot.incidents[1];
  const attackClass = topClass(attack);
  const faultClass = topClass(fault);
  const fasterBy = Math.round(
    snapshot.mttr.manual_baseline_s / snapshot.mttr.autonomous_s,
  );
  const simTime = snapshot.timeline.labels[cursor];

  const approveFix = async () => {
    setApproval("saving");
    const response = await fetch(
      `/api/approvals/${fault.decision.decision_id}`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ verdict: "approve", by: "demo-operator" }),
      },
    );
    setApproval(response.ok ? "approved" : "already resolved");
  };

  const analyzeSeed = async () => {
    setSeedStatus("analyzing telemetry…");
    setSeedFindings([]);
    try {
      const response = await fetch(
        `/api/analyze?profile=combo_night&seed=${secretSeed}`,
      );
      if (!response.ok) throw new Error(`analysis returned ${response.status}`);
      const findings = (await response.json()) as AnalyzeFinding[];
      setSeedFindings(findings);
      setSeedStatus(
        findings.length
          ? `${findings.length} independent causes found without labels`
          : "all behavior is within context",
      );
    } catch (reason) {
      setSeedStatus(reason instanceof Error ? reason.message : "analysis failed");
    }
  };

  return (
    <div className="min-h-screen bg-page text-body">
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-page/90 px-5 py-3 backdrop-blur md:px-8">
        <div className="flex items-center gap-4">
          <div className="grid h-9 w-9 place-items-center rounded-full bg-accent text-sm font-black text-accent-contrast">
            A
          </div>
          <div>
            <div className="font-serif text-xl font-semibold leading-none text-ink">Argus</div>
            <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.18em] text-muted">
              Autonomous observability
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Chip tone="border-muted/40 text-muted">Simulated telemetry</Chip>
          <span className="hidden items-center gap-2 text-xs text-success sm:flex">
            <span className="h-2 w-2 animate-pulse rounded-full bg-success" />
            reasoning online
          </span>
          <span className="tnum hidden text-xs font-bold text-ink md:inline">{simTime}</span>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-5 py-6 md:px-8">
        <section className="flex flex-col justify-between gap-5 border-b border-line pb-6 lg:flex-row lg:items-end">
          <div>
            <div className="mb-3 flex flex-wrap gap-2">
              <Chip tone="border-accent/40 bg-accent-soft text-accent">
                {snapshot.profile.replaceAll("_", " ")}
              </Chip>
              <Chip tone="border-line text-muted">seed {snapshot.seed}</Chip>
            </div>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  if (cursor >= snapshot.timeline.labels.length - 1) setCursor(0);
                  setPlaying((value) => !value);
                }}
                className="rounded-full bg-accent px-4 py-2 text-xs font-bold uppercase tracking-wider text-accent-contrast hover:bg-accent-hover"
              >
                {playing ? "Pause" : cursor >= snapshot.timeline.labels.length - 1 ? "Replay" : "Play"}
              </button>
              {([1, 10, 60] as const).map((value) => (
                <button
                  type="button"
                  key={value}
                  onClick={() => setSpeed(value)}
                  className={`rounded-full border px-3 py-2 text-xs font-bold ${
                    speed === value
                      ? "border-accent bg-accent-soft text-accent"
                      : "border-line text-muted"
                  }`}
                >
                  {value}×
                </button>
              ))}
              <input
                aria-label="Replay position"
                type="range"
                min={0}
                max={snapshot.timeline.labels.length - 1}
                value={cursor}
                onChange={(event) => {
                  setPlaying(false);
                  setCursor(Number(event.target.value));
                }}
                className="ml-1 w-48 accent-[var(--accent)]"
              />
              <span className="tnum text-xs font-bold text-muted">{simTime}</span>
              <span className="mx-1 hidden h-6 w-px bg-line lg:block" />
              <label className="flex items-center gap-2 rounded-full border border-line bg-raised px-3 py-1.5 text-xs">
                <span className="font-bold uppercase tracking-wider text-muted">Seed</span>
                <input
                  aria-label="Secret seed"
                  type="number"
                  value={secretSeed}
                  onChange={(event) => setSecretSeed(Number(event.target.value))}
                  className="tnum w-20 bg-transparent font-bold text-ink outline-none"
                />
              </label>
              <button
                type="button"
                onClick={analyzeSeed}
                className="rounded-full border border-accent/50 px-4 py-2 text-xs font-bold uppercase tracking-wider text-accent hover:bg-accent-soft"
              >
                Analyze fresh seed
              </button>
            </div>
            <h1 className="max-w-4xl text-[clamp(2.5rem,5vw,5.3rem)] leading-[0.9]">
              The attack behind the game.
            </h1>
            <p className="mt-4 max-w-3xl text-base text-body">
              Legitimate match traffic is decomposed away. Argus acts only on
              the behavioral residual, then traces a separate cascade to a real,
              inspectable commit.
            </p>
          </div>
          <div className="grid min-w-[320px] grid-cols-3 gap-2">
            {[
              ["02", "incidents"],
              ["01", "guarded action"],
              ["18", "code line"],
            ].map(([value, label]) => (
              <div key={label} className="rounded-md border border-line bg-raised p-3 shadow-sm">
                <div className="tnum font-serif text-2xl text-ink">{value}</div>
                <div className="text-[10px] font-bold uppercase tracking-[0.13em] text-muted">
                  {label}
                </div>
              </div>
            ))}
          </div>
        </section>

        {(seedStatus || seedFindings.length > 0) && (
          <section className="mt-5 rounded-lg border border-accent/30 bg-accent-soft p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-accent">
                  Fresh-seed fire drill
                </p>
                <h2 className="mt-1">
                  Seed {secretSeed}: {seedStatus}
                </h2>
              </div>
              <Chip tone="border-accent/40 text-accent">runtime labels isolated</Chip>
            </div>
            {seedFindings.length > 0 && (
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                {seedFindings.map((finding) => (
                  <article
                    key={`${finding.rca.cause_class}-${finding.rca.origin.service}`}
                    className="rounded-md border border-line bg-raised p-4"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <Chip tone="border-line text-muted">{finding.rca.cause_class}</Chip>
                      <span className="text-xs font-bold uppercase tracking-wider text-accent">
                        {finding.decision.decision}
                      </span>
                    </div>
                    <h3 className="mt-3">{finding.rca.origin.service}</h3>
                    {finding.rca.code_fault && (
                      <p className="mt-1 font-mono text-xs text-warning">
                        {finding.rca.code_fault.file}:{finding.rca.code_fault.line}
                      </p>
                    )}
                    <p className="mt-3 line-clamp-3 text-xs text-muted">
                      {finding.decision.reason}
                    </p>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        <div className="mt-6 grid gap-5 xl:grid-cols-[1.35fr_0.65fr]">
          <section className="rounded-lg border border-line bg-raised p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">
                  Surge decomposition
                </p>
                <h2 className="mt-1">Expected crowd. Unexpected behavior.</h2>
              </div>
              <div className="flex gap-2">
                <Chip tone="border-success/40 text-success">event explained</Chip>
                <Chip tone="border-danger/40 text-danger">residual isolated</Chip>
              </div>
            </div>
            <div className="mt-4">
              <DecompositionChart timeline={snapshot.timeline} cursor={cursor} />
            </div>
            <div className="mt-3 grid gap-3 border-t border-line pt-4 md:grid-cols-3">
              <div>
                <div className="text-xs font-bold text-ink">Base demand</div>
                <p className="mt-1 text-xs text-muted">Seasonal baseline from warmup history.</p>
              </div>
              <div>
                <div className="text-xs font-bold text-accent">Event envelope</div>
                <p className="mt-1 text-xs text-muted">Known Cup Final multiplier, suppressed as context.</p>
              </div>
              <div>
                <div className="text-xs font-bold text-danger">Residual</div>
                <p className="mt-1 text-xs text-muted">Auth failures and client fingerprints deform.</p>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-line bg-raised p-5 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">
              Decision feed
            </p>
            <div className="mt-4 space-y-4">
              <article className="rounded-md border border-danger/30 bg-danger/5 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <Chip tone="border-danger/40 text-danger">{attackClass.class}</Chip>
                    <h3 className="mt-3">Anomalous login cohort</h3>
                  </div>
                  <span className="tnum text-xl font-bold text-danger">
                    {Math.round(attack.verdict.confidence * 100)}%
                  </span>
                </div>
                <p className="mt-3 text-sm">{attack.decision.reason}</p>
                {attack.action && (
                  <div className="mt-4 rounded-sm border border-line bg-page p-3">
                    <div className="flex justify-between text-xs">
                      <span className="font-bold uppercase tracking-wider text-accent">
                        {attack.action.rung.replaceAll("_", " ")}
                      </span>
                      <span className="tnum text-muted">
                        max {attack.action.target.est_traffic_pct}%
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-muted">
                      {attack.action.expected_effect}
                    </p>
                    <p className="mt-2 text-xs font-bold text-success">
                      Protected cohorts touched:{" "}
                      {attack.action.blast_radius.protected_cohorts_touched}
                    </p>
                  </div>
                )}
              </article>

              <article className="rounded-md border border-warning/30 bg-warning/5 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <Chip tone="border-warning/40 text-warning">{faultClass.class}</Chip>
                    <h3 className="mt-3">Retry amplification cascade</h3>
                  </div>
                  <span className="tnum text-xl font-bold text-warning">
                    {Math.round(fault.verdict.confidence * 100)}%
                  </span>
                </div>
                <p className="mt-3 text-sm">{fault.decision.reason}</p>
                <div className="mt-4 border-l-2 border-warning pl-3 text-xs text-muted">
                  Act with a reversible caller throttle + code fix. No automatic patching.
                </div>
                <button
                  type="button"
                  onClick={approveFix}
                  disabled={approval === "saving" || approval === "approved"}
                  className="mt-4 rounded-full border border-warning/50 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-warning disabled:opacity-60"
                >
                  {approval === "approved"
                    ? "Operator approved"
                    : approval === "saving"
                      ? "Recording…"
                      : approval || "Approve interim throttle"}
                </button>
              </article>
            </div>
          </section>
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-[0.82fr_1.18fr]">
          <section className="rounded-lg border border-line bg-raised p-5 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">
              Causal collapse
            </p>
            <div className="mt-4 flex items-center gap-3">
              <div className="grid h-12 w-12 place-items-center rounded-full border-2 border-warning bg-warning/10 font-bold text-warning">
                P
              </div>
              <div>
                <h2>{fault.rca.origin.service}</h2>
                <p className="text-xs text-muted">one origin · ranked alternates retained</p>
              </div>
              <div className="ml-auto tnum text-2xl font-bold text-ink">
                {Math.round(fault.rca.confidence * 100)}%
              </div>
            </div>
            <ol className="mt-5 space-y-3">
              {fault.rca.collapse_trace.slice(0, 4).map((line, index) => (
                <li key={line} className="flex gap-3 text-sm">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-sidebar text-xs font-bold text-muted">
                    {index + 1}
                  </span>
                  <span>{line}</span>
                </li>
              ))}
            </ol>
            <div className="mt-5 rounded-md border border-line bg-sidebar p-4">
              <div className="text-xs font-bold uppercase tracking-wider text-ink">Cure</div>
              <p className="mt-2 text-sm">{fault.rca.cure.justification}</p>
              <p className="mt-2 text-xs text-accent">
                Interim: {fault.rca.cure.interim_infra_action}
              </p>
            </div>
          </section>

          {fault.rca.code_fault && (
            <section className="overflow-hidden rounded-lg border border-line bg-raised shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">
                    Real code finding
                  </p>
                  <h2 className="mt-1">
                    {fault.rca.code_fault.file}:{fault.rca.code_fault.line}
                  </h2>
                </div>
                <Chip tone="border-success/40 text-success">git show verified</Chip>
              </div>
              <div className="grid lg:grid-cols-[0.58fr_0.42fr]">
                <div className="border-b border-line p-5 lg:border-r lg:border-b-0">
                  <div className="font-mono text-xs text-muted">
                    commit {fault.rca.code_fault.commit.slice(0, 12)}
                  </div>
                  <p className="mt-3 text-sm text-ink">{fault.rca.code_fault.mechanism}</p>
                  <div className="mt-4 max-h-56 overflow-auto rounded-sm bg-code p-4 font-mono text-[11px] leading-5 text-body">
                    {fault.rca.code_fault.proposed_fix?.diff
                      .split("\n")
                      .slice(0, 18)
                      .map((line) => (
                        <div
                          key={line}
                          className={
                            line.startsWith("+")
                              ? "text-success"
                              : line.startsWith("-")
                                ? "text-danger"
                                : ""
                          }
                        >
                          {line || " "}
                        </div>
                      ))}
                  </div>
                </div>
                <div className="p-5">
                  <div className="text-xs font-bold uppercase tracking-wider text-ink">
                    Proposed repair
                  </div>
                  <p className="mt-3 text-sm">
                    {fault.rca.code_fault.proposed_fix?.summary}
                  </p>
                  <div className="mt-5 space-y-2">
                    {fault.verdict.evidence.slice(0, 3).map((item) => (
                      <div key={item.note} className="flex gap-2 text-xs text-muted">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
                        {item.note}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </section>
          )}
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[0.7fr_0.7fr_0.6fr]">
          <section className="rounded-lg border border-line bg-raised p-5 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">
              Behavior ratios
            </p>
            <h2 className="mt-1">Volume rises. Ratios should not.</h2>
            <div className="mt-5 grid grid-cols-2 gap-3">
              {Object.entries(snapshot.ratios).map(([name, values]) => {
                const minimum = Math.min(...values);
                const maximum = Math.max(...values);
                const delta = maximum - minimum;
                const deformed = delta > Math.max(Math.abs(minimum) * 0.15, 0.05);
                return (
                  <div key={name} className="rounded-md border border-line bg-sidebar p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-bold capitalize text-ink">{name}</span>
                      <span
                        className={`h-2 w-2 rounded-full ${
                          deformed ? "bg-danger" : "bg-success"
                        }`}
                      />
                    </div>
                    <svg viewBox="0 0 120 34" className="mt-3 h-10 w-full" aria-hidden="true">
                      <polyline
                        fill="none"
                        stroke={deformed ? "var(--danger)" : "var(--success)"}
                        strokeWidth="2"
                        points={values
                          .map((value, index) => {
                            const x = (index / (values.length - 1)) * 120;
                            const y =
                              30 -
                              ((value - minimum) / Math.max(delta, 0.0001)) * 26;
                            return `${x},${y}`;
                          })
                          .join(" ")}
                      />
                    </svg>
                    <div className="mt-1 text-[10px] uppercase tracking-wider text-muted">
                      {deformed ? "deformed" : "in band"}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded-lg border border-line bg-raised p-5 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">
              Service topology
            </p>
            <h2 className="mt-1">One world model. One origin.</h2>
            <div className="mt-5 space-y-3">
              {snapshot.topology.services.map((service) => {
                const isOrigin = service === snapshot.topology.origin;
                const isTarget = service === snapshot.topology.attack_target;
                return (
                  <div
                    key={service}
                    className={`flex items-center gap-3 rounded-md border p-3 ${
                      isOrigin
                        ? "border-warning/50 bg-warning/5"
                        : isTarget
                          ? "border-danger/50 bg-danger/5"
                          : "border-line bg-sidebar"
                    }`}
                  >
                    <span
                      className={`grid h-8 w-8 place-items-center rounded-full text-xs font-black ${
                        isOrigin
                          ? "bg-warning text-page"
                          : isTarget
                            ? "bg-danger text-page"
                            : "bg-page text-muted"
                      }`}
                    >
                      {service.slice(0, 1).toUpperCase()}
                    </span>
                    <span className="text-sm font-bold text-ink">{service}</span>
                    <span className="ml-auto text-[10px] font-bold uppercase tracking-wider text-muted">
                      {isOrigin ? "root cause" : isTarget ? "attack target" : "healthy"}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded-lg border border-line bg-raised p-5 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted">
              Auditable outcome
            </p>
            <div className="mt-3 rounded-md border border-success/30 bg-success/5 p-4">
              <div className="tnum font-serif text-5xl text-success">{fasterBy}×</div>
              <p className="mt-2 text-sm font-bold text-ink">faster than manual baseline</p>
              <p className="mt-1 text-xs text-muted">
                {snapshot.mttr.autonomous_s.toFixed(0)}s autonomous vs{" "}
                {(snapshot.mttr.manual_baseline_s / 3600).toFixed(0)}h manual.
              </p>
            </div>
            <div className="mt-4 space-y-2">
              {snapshot.audit.map((row, index) => (
                <div
                  key={`${row.type}-${index}`}
                  className="flex items-center gap-3 border-b border-line py-2 text-xs last:border-0"
                >
                  <span className="tnum text-muted">{String(index + 1).padStart(2, "0")}</span>
                  <Chip
                    tone={
                      row.type === "action"
                        ? "border-accent/40 text-accent"
                        : row.type === "mttr"
                          ? "border-success/40 text-success"
                          : "border-line text-muted"
                    }
                  >
                    {row.type}
                  </Chip>
                  <span className="truncate text-ink">
                    {row.rung ?? row.decision ?? row.incident_id}
                  </span>
                </div>
              ))}
            </div>
            <a
              href="/api/audit/export.ndjson"
              className="mt-4 inline-flex text-xs font-bold uppercase tracking-wider text-accent hover:text-accent-hover"
            >
              Export audit trail →
            </a>
          </section>
        </div>
      </main>
    </div>
  );
}
