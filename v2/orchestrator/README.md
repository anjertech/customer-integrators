# orchestrator

The dispatcher. Reads `tenants.json` from S3 and creates **one worker Job per
enabled tenant** via the Kubernetes API, stamping the worker Job template with a
unique name + `--tenant <id>` + the tenant's VPN Secret. Runs as a Job, triggered
by a CronJob.

## Config (env)
| Var | Required | Meaning |
| --- | --- | --- |
| `TENANTS_S3` | yes | `s3://bucket/tenants.json` |
| `NAMESPACE` | no | namespace to create worker Jobs in (default `etl`) |
| `WORKER_JOB_TEMPLATE` | no | template path (default `/app/worker-job.template.yaml`) |
| `IMAGE_WORKER` | yes | worker image (ECR) — substituted into the template |
| `IMAGE_VPN_SIDECAR` | yes | sidecar image (ECR) |
| `SCRIPTS_S3_PREFIX` | yes | S3 prefix for scripts (passed to the worker) |
| `AWS_REGION` | no | default `us-east-2` |

`${VAR}` placeholders in `worker-job.template.yaml` are filled from these at render
time; per-tenant fields (name, `--tenant`, VPN secret) are set in code.

## What it stamps per tenant
- `metadata.name` = `etl-<tenant>-<timestamp>`, `labels.tenant` = `<id>`
- worker container `args` = `["--tenant", "<id>"]`
- vpn-sidecar `env.TENANT_ID` = `<id>` (the sidecar then self-fetches its secret)

## AWS access
Runs under the **`orchestrator`** ServiceAccount → Pod Identity role scoped to read
`tenants.json` from S3. The worker pods it creates use the separate **`worker`**
role; **both the worker and the sidecar self-fetch** their per-tenant secrets from
Secrets Manager via that role (no External Secrets needed).

## Still needed to actually run (the k8s / Helm phase)
- **RBAC:** `orchestrator` ServiceAccount + Role allowing `create`/`list` Jobs in `etl`.
- **CronJob** that runs this image on a schedule.
- Image tags + the `IMAGE_*` / `*_S3` env wired via Helm values.
