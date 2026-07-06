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
        └─► Worker Job   (one per ENABLED tenant, stamped with --tenant <id>)
              Pod = [ vpn-sidecar ] + [ worker ]   (native sidecar + main container)
                vpn-sidecar: self-fetches its VPN secret → openfortivpn → client network
                worker:      self-fetches its Oracle creds + script (from --tenant id),
                             runs the script against the client's Oracle DB
```

## Components
| Dir | What | Image |
|---|---|---|
| `orchestrator/` | Python dispatcher — reads the tenant list, creates one worker Job per tenant via the Kubernetes API (holds `worker-job.template.yaml`) | ECR `orchestrator` |
| `worker/` | Script-agnostic Python runner — Oracle thick-mode client baked in; self-fetches its secret + script and runs it | ECR `worker` |
| `vpn-sidecar/` | `openfortivpn` (+ optional SSH tunnels); isolates the privileged `NET_ADMIN`/`/dev/ppp` networking; self-fetches its VPN secret via awscli | ECR `vpn-sidecar` |
| `scripts/` | Per-tenant ETL scripts + `test_oracle_connection.py` (smoke test). Live scripts are uploaded to S3. | — |
| `chart/` | Helm chart — namespace + ServiceAccounts + RBAC + the orchestrator CronJob | — |
| `eks-test/` | No-VPN EKS validation: in-cluster mock Oracle + runbook to prove the pipeline without client creds | — |
| `docker-compose.yml` | Local full-chain test (sidecar + worker as one "pod") | — |

## How it maps to the v2 infra
- **Namespace `etl`** + ServiceAccounts `orchestrator` / `worker` — already wired to
  **Pod Identity** roles (orchestrator → S3 read; worker → Secrets Manager + S3).
- **Karpenter ETL NodePool** — worker pods tolerate `workload=etl:NoSchedule`, so they
  land on the dedicated On-Demand ETL nodes, off the API/dashboard nodes.
- **ECR** repos `orchestrator`, `worker`, and `vpn-sidecar` hold the images.
- **Egress** leaves via the NAT gateway's Elastic IP — the address clients allow-list.
- Tenant **secrets** live in AWS Secrets Manager under `presa/etl/<tenant>`; both the
  sidecar and worker **self-fetch** theirs via Pod Identity (the `worker` role is
  scoped to `presa/*`) — no External Secrets.
- The tenant **list** (`tenants.json`) and **scripts** live in S3.

## Tenant model
A tenant is a **client** that owns **many dealerships**, each with its **own Oracle
database** — a private IP on the client's network, reached over **one VPN** (a few are
`no_route` and need a dedicated SSH tunnel). So: **one worker pod per client → one VPN
→ many DBs**, and the tenant's *script* iterates over those DBs.

`tenants.json` (in S3) is the source of truth. Each entry is `{ id, enabled, script }`
plus optional `files`, `args`, `env`, and `secret` fields (see
`tenants.example.json`). From a tenant's `id`, the worker derives:
- its **secret** by convention → `presa/etl/<id>` (Secrets Manager), and
- its **script bundle** by looking up `script`/`files` → fetched from S3.

`args` and `env` support `${ENV_VAR}` placeholders expanded after the tenant secret
is loaded, so scripts that still require flags like `--password`, `--table`, or
`--db-key` can be run without baking tenant-specific values into the image.

So **onboarding a tenant is pure data**: create the `presa/etl/<id>` secret, upload its
script to S3, add a line to `tenants.json` — no redeploy, no new Kubernetes objects.

## Status (connectivity-first — the real FortiGate dial is the last risk)
- [x] **Connectivity half (code)** — `vpn-sidecar/` + `worker/` + `scripts/test_oracle_connection.py` + `docker-compose.yml`
- [x] **Worker proven locally** — `SELECT 1 FROM DUAL` against a mock Oracle (Stage 1)
- [x] **orchestrator + Helm chart** — `--tenant` dispatch, `chart/` (namespace/SAs/RBAC/CronJob), self-fetch (no External Secrets)
- [x] **Proven on EKS (no-VPN)** — orchestrator → per-tenant worker Jobs → mock Oracle → `SELECT 1`, fanned out over 3 tenants. See `eks-test/`.
- [ ] **Prove the real `openfortivpn` dial** — needs client FortiGate creds + `/dev/ppp` on the EKS node (the one unproven piece)
- [ ] **First real per-tenant script** (upload the current `fetch_and_send*` script
      bundle from `../core` and wire the tenant args/env)

### Local run
```bash
cp .env.example .env        # fill in VPN_* and ORACLE_* (one routable dealership DB)
docker compose up --build   # success = worker logs "SELECT 1 FROM DUAL): 1" and exits 0
```
