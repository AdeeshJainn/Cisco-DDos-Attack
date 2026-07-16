# Argus

**When traffic spikes, is it your fans, an attacker, or your own bad deploy?**
Argus is an autonomous observability engine that answers that question live —
and acts on it. It decomposes every surge into *expected* (a scheduled event),
*unexplained residual* (a possible attack hiding inside the crowd), and
*self-inflicted* (a fault your own code shipped), then takes graded, reversible
remediation with a stated reason for every decision.

## The problem

A live event and a DDoS look identical on a request-rate graph. Traditional
monitoring either pages a human for both (alert fatigue) or suppresses both
(missed attack). And when the surge exposes a latent bug — a retry storm, an
exhausted pool — the symptom storm points everywhere except the one commit that
caused it. Root-causing that by hand takes hours.

## The idea

**An event explains volume, not behavior.** Fan traffic multiplies request
rates but preserves behavioral ratios: IP entropy, SYN:ACK balance,
auth-failure rate, client-fingerprint mix. Attacks deform those ratios;
internal faults deform latency and saturation instead. Argus builds an
expected-traffic band from the event calendar, monitors the ratios
independently, and classifies what the band cannot explain — down to the
originating service, file, line and commit when the cause is code.

## Architecture

```
telemetry ──► detection ──────► verdict ─────► policy ────────► actions
  stream       expected band     expected        suppress         rate-limit /
  (replayed     + residual       surge /         alert            throttle /
   scenarios)   behavioral       attack /        act              scale / isolate
                ratios           fault /            │                 │
                     │           combination        │             rollback watch
                     ▼                              ▼                 │
                  symptoms ──► RCA: cluster ► collapse to origin      ▼
                               ► localize file:line:commit ──► audit log,
                               ► propose fix                   reports, MTTR
```

Engine: Python / FastAPI, streaming decisions over WebSocket.
Dashboard: React + ECharts mission control that replays the full timeline and
shows every decision — with its reason and evidence — as it happens.

## Quickstart

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 20+,
npm, and Git.

```sh
make setup
make test
make demo
```

Open `http://127.0.0.1:8100`. The production dashboard and FastAPI engine are
served from one process. The screen includes:

- event/base/residual surge decomposition;
- attack and code-fault verdicts with the exact decision reason;
- a protected-cohort-aware rate-limit action;
- causal collapse to one origin service;
- a real commit, file, line, mechanism, and repair diff.

The scenario engine also accepts arbitrary integer seeds:

```sh
make seeds N=1 START_SEED=9001 PROFILE=combo_night
make replay PROFILE=match_night SEED=9001 SPEED=60
```

Available profiles are `quiet_day`, `match_night`, `cascade_night`, and
`combo_night`. Generated telemetry and labels are disposable artifacts under
`scenarios/` or `var/scenarios/`; they are intentionally not committed.

To score a prediction file against generated ground truth:

```sh
LABELS=scenarios/combo_night-seed-9001.labels.json \
PREDICTIONS=predictions.json \
make score
```

Every suppress, alert, or act decision carries a populated human-readable
reason and evidence reference. `make test` checks contract validity, label
isolation, deterministic generation, fresh-seed behavior, one-origin RCA,
real-history line localization, protected cohorts, rollback restoration, and
dashboard types/tests.

## Honesty note

Telemetry is simulated: it is seeded, deterministic, replayable, and clearly
marked as such in the dashboard. The system under diagnosis is a real,
runnable five-service demo application.

`make setup` materializes a deterministic **inner Git repository** inside
`demo-app/`. Its fault commits contain the actual bad diffs used by the
scenario deploy feed, and its later commits contain the repairs. This inner
history is diagnostic evidence, not the submission repository's development
history. When Argus reports a hash, judges can verify the claim directly:

```sh
git -C demo-app show <reported-commit>
```

The repair proposal is also offline-safe: it is extracted from the real repair
commit, so the demo does not depend on an external model or network access.
