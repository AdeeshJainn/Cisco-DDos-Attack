import { HelloChart } from "./components/hello-chart";
import { ThemeToggle } from "./components/theme-toggle";

export default function App() {
  return (
    <div className="min-h-screen bg-page">
      <header className="flex items-center justify-between border-b border-line px-6 py-3">
        <span className="font-serif text-2xl font-semibold text-ink">
          Argus
        </span>
        <ThemeToggle />
      </header>
      <main className="mx-auto max-w-3xl px-6 py-16">
        <h1>Watching the whole timeline.</h1>
        <p className="mt-6 max-w-xl text-body">
          Surge decomposition, cause classification, code-level root-cause
          analysis and graded remediation — replayed as the decisions happen.
          The mission-control dashboard lands here.
        </p>
        <section className="mt-12 rounded-lg border border-line bg-raised p-6 shadow-sm">
          <h3 className="mb-4">Telemetry preview</h3>
          <HelloChart />
        </section>
      </main>
    </div>
  );
}
