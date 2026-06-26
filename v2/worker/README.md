# worker

Script-agnostic Python ETL runner. Waits for the **vpn-sidecar**, then runs the
per-tenant script with the Oracle thick-mode client. The worker stays unprivileged —
all VPN/SSH lives in the sidecar.

The image bakes in the **Oracle Instant Client** (thick mode; legacy DBs reject thin
mode) and `oracle_client.py` (importable by any script).

## Invocation
- **Production:** `worker --tenant <id>` — the orchestrator stamps this arg into
  each Job. The worker derives everything from the id (script + secret); AWS access
  comes from the shared `worker` Pod Identity role.
- **Local test:** no `--tenant` — configure via env (used for the Stage-1 test).

## Config (env)
| Var | Mode | Meaning |
| --- | --- | --- |
| `TENANTS_S3` | prod | `s3://bucket/tenants.json` (looked up by `--tenant` for the script) |
| `SCRIPTS_S3_PREFIX` | prod | S3 prefix for scripts; joined with the tenant entry's `script` |
| `READY_FILE` | both | VPN readiness marker to wait for (default `/shared/vpn-ready`) |
| `WAIT_FOR_VPN` | both | `false` to skip the VPN wait (local mock-Oracle testing) |
| `VPN_WAIT_TIMEOUT` | both | seconds to wait for the marker (default `120`) |
| `SCRIPT_S3` | local | `s3://bucket/key` of a script (alternative to `--tenant`) |
| `SCRIPT_PATH` | local | local script path (default `/scripts/run.py`) |
| `ORACLE_SECRET` | local | Secrets Manager secret holding `oracle` creds |
| `AWS_REGION` | both | region for Secrets Manager (default `us-east-2`) |
| `ORACLE_HOST/PORT/SERVICE/SID/USER/PASSWORD` | local | passed straight to the script if no secret is used |

In `--tenant` mode the secret name is the tenant entry's `secret`, or by convention
`presa/etl/<id>`. The script always receives the Oracle connection as `ORACLE_*` env
vars and uses `oracle_client.initialize_oracle_thick_mode()`.

## Build
```bash
docker build -t presa/worker:dev customer-integrators/v2/worker
# arm64 (e.g. Apple Silicon native): pass an aarch64 Instant Client URL via
#   --build-arg ORACLE_IC_URL=<...linux-arm64.zip>
```
