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
| `PROGRESS_S3_PREFIX` | prod | optional base S3 prefix for per-tenant `progress*.json` restore/upload |
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

## Tenant script bundles

The worker can run the current `fetch_and_send*` scripts without baking them into
the image. A tenant entry may include:

- `script`: entry-point file under `SCRIPTS_S3_PREFIX`
- `files`: helper files to download beside the script, for imports like
  `gmuni_mappings.py`, `universidad_common.py`, or `refran_common.py`
- `args`: argv passed to the script; `${ENV_VAR}` placeholders are expanded after
  the worker loads the tenant secret
- `env`: environment variables added before running the script; values also support
  `${ENV_VAR}` placeholders

The tenant secret can contain the sidecar VPN config and worker config together:

```json
{
  "vpn": { "gateway": "vpn.example.com:443", "username": "...", "password": "..." },
  "oracle": { "host": "127.0.0.1", "port": 16223, "service": "SISTEMAS", "user": "PRESA", "password": "..." },
  "env": {
    "PRESA_TENANT_ID": "mxa",
    "PRESA_CLIENT_ID": "mxa",
    "PRESA_CLIENT_SECRET": "...",
    "UNIVERSIDAD_ODBC_CONNECTION_STRING": "DRIVER={ODBC Driver 18 for SQL Server};..."
  }
}
```

For tenant runs, `PROGRESS_S3_PREFIX` is treated as a base prefix and the worker
uses `<prefix>/<tenant-id>/`. When set, it restores matching `progress*.json` files
into the script directory before execution and uploads them back afterward. This is
only a fallback for scripts that have not moved to backend idempotency yet.

## Build
```bash
docker build -t presa/worker:dev customer-integrators/v2/worker
# arm64 (e.g. Apple Silicon native): pass an aarch64 Instant Client URL via
#   --build-arg ORACLE_IC_URL=<...linux-arm64.zip>
```
