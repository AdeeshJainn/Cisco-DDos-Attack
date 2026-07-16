# demo-app — the storefront the incidents happen to

A compact five-service storefront: an edge gateway fronting auth, catalog and
payment, with payment fanning out to a notification service.

```
edge-gw ──► auth-svc
   ├──────► catalog-svc
   └──────► payment-svc ──► notify-svc
```

[`topology.yaml`](topology.yaml) is the single world model — service names,
code directories, call edges, per-service scale and capacity. The scenario
generator and Argus's root-cause analysis read the same file, so the world
that produces the telemetry and the graph RCA reasons over can never drift
apart.

## What is real here, and what is not

This codebase exists to be diagnosed: faults are injected into it and Argus
has to trace them back. We are explicit about where the line sits.

- **The code is real.** Each service is a small, readable, dependency-free
  Python program — handlers, a retry helper, a cache layer, a connection
  pool. You can open any file and run it.
- **The git history is real.** `demo-app/.git` is materialized by
  `make setup` from a scripted timeline (`history/manifest.yaml` +
  `history/patches/`) with pinned dates and identities, so commit hashes are
  byte-stable on every machine. When RCA names a commit,
  `git -C demo-app show <hash>` displays the actual offending diff on the
  actual file and line.
- **The traffic is simulated.** No cluster runs these services during a
  replay; telemetry comes from the scenario engine, which drives load through
  the capacity model declared in `topology.yaml`.

## Services

| Service | Directory | Role |
|---|---|---|
| edge-gw | `edge_gw/` | Public entry point; routes to the backends, bounds concurrency, times out fast |
| auth-svc | `auth_svc/` | Login + token verification over a fixed-size DB connection pool |
| catalog-svc | `catalog_svc/` | Product listings; TTL cache in front of batched database reads |
| payment-svc | `payment_svc/` | Charge capture; receipt fan-out to notify-svc with bounded retries |
| notify-svc | `notify_svc/` | Provider handoff for receipts/alerts; bounded recent-delivery ring |

## Running a service locally

Every service is stdlib-only Python 3.11 — no installs. Each takes its port
from `PORT` and its upstream addresses from environment variables (defaults
match `topology.yaml`):

```sh
cd demo-app
python notify_svc/server.py &
python payment_svc/server.py &
python auth_svc/server.py &
python catalog_svc/server.py &
python edge_gw/gateway.py
```

Then, for example:

```sh
curl -s 'http://localhost:8080/products?ids=42,7'
curl -s -X POST 'http://localhost:8080/checkout' \
  -d '{"order_id": "o-1", "amount_cents": 4999, "email": "ava@example.com"}'
```
