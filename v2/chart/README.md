# presa-etl Helm chart

Deploys the ETL **orchestrator** as a CronJob, plus the RBAC and ServiceAccounts it
and the workers need. The orchestrator creates per-tenant worker Jobs at runtime;
the sidecar + worker **self-fetch** their secrets from Secrets Manager (Pod
Identity), so there are no ExternalSecret resources here.

## What it installs
- `Namespace` `etl` with `pod-security.kubernetes.io/enforce: privileged` (the
  sidecar runs privileged for openfortivpn)
- `ServiceAccount` **orchestrator** and **worker** — names must match the EKS Pod
  Identity associations created in the infra
- `Role` + `RoleBinding` letting `orchestrator` create/list/delete Jobs
- `CronJob` running the orchestrator on a schedule

## Prerequisites
1. The **v2 EKS infra** applied (cluster + Pod Identity roles for `etl/orchestrator`
   and `etl/worker`).
2. **ECR repos** for `orchestrator`, `worker`, and `vpn-sidecar`. The current
   `infrastructure/v2` dev root creates all three.
3. Images **built + pushed** to those repos (tags wired via values).
4. `tenants.json` uploaded to the `tenantsS3` location; script bundles copied from
   the current `../core` scripts under `scriptsS3Prefix`.

## Install
Create + label the namespace first (Helm stores the release in it, and the sidecar
needs a privileged-PSS namespace), then install:
```bash
kubectl create namespace etl
kubectl label namespace etl pod-security.kubernetes.io/enforce=privileged --overwrite

helm upgrade --install presa-etl ./chart -n etl \
  --set image.registry=853982915722.dkr.ecr.us-east-2.amazonaws.com \
  --set image.orchestrator.tag=<sha> --set image.worker.tag=<sha> --set image.vpnSidecar.tag=<sha>
```
(`namespace.create` defaults to `false`. Set it `true` only if you install the
release into a *different*, existing namespace and let the chart create `etl`.)

## Key values
| Value | Default | Meaning |
| --- | --- | --- |
| `schedule` | `0 6 * * *` | CronJob schedule (UTC) |
| `tenantsS3` | `s3://presa-etl/tenants.json` | tenant list |
| `scriptsS3Prefix` | `s3://presa-etl/scripts` | script prefix |
| `progressS3Prefix` | empty | optional fallback prefix for legacy per-tenant `progress*.json` sync |
| `region` | `us-east-2` | AWS region |
| `image.*` | dev ECR | registry + per-image repo/tag |

## Notes
- The **worker Job template** is baked into the orchestrator image
  (`worker-job.template.yaml`); to manage it from the chart instead, mount it as a
  ConfigMap and set `WORKER_JOB_TEMPLATE`.
- Trigger a run without waiting for the schedule:
  `kubectl create job -n etl --from=cronjob/presa-etl-orchestrator manual-1`
