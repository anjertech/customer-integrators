# PRESA ETL — v2 (EKS-native)

Per-tenant ETL that pulls data from client **Oracle** databases into the presa
SaaS, rebuilt to run on the **v2 EKS infrastructure** (`presa/infrastructure/v2`).
This is a fresh rewrite with the full production context in mind (real
`openfortivpn`, Pod Identity, Karpenter ETL pool) — it supersedes the root `*.py`
integrators, `pods/`, and `applications/`.

## The chain
```
CronJob (schedule)
  └─► Orchestrator Job  (Python)            reads tenants.json from S3
        └─► Worker Job   (one per ENABLED tenant)
              Pod = [ vpn-sidecar ] + [ worker ]   (two containers, shared netns)
                vpn-sidecar: openfortivpn → client network → SSH jump → local port-forward
                worker:      pulls the tenant script from S3 + Oracle creds from
                             Secrets Manager, runs the script against the forwarded port
```

## Components
| Dir | What | Image |
|---|---|---|
| `orchestrator/` | Python dispatcher — reads the tenant list, creates one worker Job per tenant via the Kubernetes API | ECR `orchestrator` |
| `worker/` | Script-agnostic Python runner — Oracle thick-mode client baked in; runs the per-tenant script | ECR `worker` |
| `vpn-sidecar/` | `openfortivpn` + SSH tunnel; isolates the privileged `NET_ADMIN`/tun networking from the worker | part of the worker pod |
| `scripts/` | Per-tenant ETL scripts + the `select-1` smoke test (the live source of truth lives in S3) | — |
| `k8s/` | CronJob, RBAC, namespace, worker Job template | — |

## How it maps to the v2 infra
- **Namespace `etl`** + ServiceAccounts `orchestrator` / `worker` — already wired to
  **Pod Identity** roles (orchestrator → S3 read; worker → Secrets Manager + S3).
- **Karpenter ETL NodePool** — worker pods tolerate `workload=etl:NoSchedule`, so they
  land on the dedicated On-Demand ETL nodes, off the API/dashboard nodes.
- **ECR** repos `orchestrator` and `worker` hold the images.
- **Egress** leaves via the NAT gateway's Elastic IP — the address clients allow-list.
- Tenant **secrets** live in AWS Secrets Manager under `presa/etl/<tenant>` (the worker
  role is scoped to `presa/*`).
- The tenant **list** (`tenants.json`) and **scripts** live in S3.

## Tenant model (finalized later, at the orchestrator phase)
A tenant is a **client** that owns **many dealerships**, each with its **own Oracle
database** — a private IP on the client's network, reached over **one VPN** (a few are
`no_route` and need a dedicated SSH tunnel). So: **one tenant → one VPN → many DBs**,
which is how the existing `fetch_and_send_*` scripts already work (a dict of ~20
dealership hosts they iterate over).

The exact `tenants.json` schema + Secrets Manager layout are **deferred** until we build
the orchestrator — they don't affect the connectivity half (vpn-sidecar + worker), which
is **script-agnostic**. `tenants.example.json` is a placeholder, not the final shape.
Tentative boundary (not locked): **one worker pod per client**, iterating its DBs.

## Build order (connectivity-first — real FortiGate dial is the riskiest part)
- [x] **Connectivity half (code)** — `vpn-sidecar/` + `worker/` + `scripts/test_oracle_connection.py` + `docker-compose.yml`
- [x] **Prove `SELECT 1 FROM DUAL`** — worker half proven locally (Stage 1); VPN (Stages 2–3) assumed
- [x] **orchestrator (code)** — `orchestrator/` dispatcher + `worker-job.template.yaml`; worker accepts `--tenant`
- [x] **k8s deploy wiring (Helm)** — `chart/`: namespace (PSS privileged) + SAs + RBAC + CronJob (self-fetch, no External Secrets)
- [ ] **Deploy + prove on EKS** — add `vpn-sidecar` ECR repo, build/push images, `helm install`, run → `SELECT 1` on a real node
- [ ] **first real per-tenant script**

### Local run
```bash
cp .env.example .env        # fill in VPN_* and ORACLE_* (one routable dealership DB)
docker compose up --build   # success = worker logs "SELECT 1 FROM DUAL): 1" and exits 0
```
