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
    observed: number[];
  };
  incidents: IncidentBundle[];
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

  useEffect(() => {
    fetch("/api/demo")
      .then((response) => {
        if (!response.ok) throw new Error(`demo API returned ${response.status}`);
        return response.json() as Promise<DemoSnapshot>;
      })
      .then(setSnapshot)
      .catch((reason: Error) => setError(reason.message));
  }, []);

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
              <DecompositionChart timeline={snapshot.timeline} />
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
                  Alert + code fix. No automatic patching; interim caller throttle proposed.
                </div>
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
      </main>
    </div>
  );
}
