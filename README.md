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

```sh
make setup   # engine venv (uv) + dashboard deps
make test    # full local suite
```

Replay, scoring and the single-command demo are landing incrementally; each
Make target tells you where it stands.

## Honesty note

Telemetry is simulated (seeded, deterministic, replayable) — but the codebase
under diagnosis is real: a five-service demo application with a real git
history whose fault commits are actually there. When Argus names a commit, you
can `git show` it.
