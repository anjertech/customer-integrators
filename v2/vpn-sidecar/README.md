# vpn-sidecar

Dials the client's **FortiGate** with `openfortivpn`, optionally opens **SSH
tunnels** for `no_route` databases, then writes a **readiness marker** to a shared
volume. The worker waits for that marker before connecting. All the privileged
networking lives here, keeping the worker unprivileged.

## Modes
- **Production:** set `TENANT_ID` (and `AWS_REGION`). The sidecar **self-fetches**
  its VPN config from Secrets Manager (`presa/etl/<TENANT_ID>`, or `SECRET_NAME`)
  using the pod's Pod Identity — same model as the worker. Expected secret JSON:
  ```json
  { "vpn": { "gateway": "...", "username": "...", "password": "...", "trusted_cert": "..." },
    "ssh": { "jump": "user@host", "forwards": "lport:rhost:rport", "private_key": "..." } }
  ```
- **Local test:** provide `VPN_GATEWAY/USERNAME/PASSWORD` directly via env — the
  self-fetch is skipped, no AWS needed (used by docker-compose).

## Config (env)
| Var | Mode | Meaning |
| --- | --- | --- |
| `TENANT_ID` | prod | tenant id → self-fetch `presa/etl/<id>` |
| `SECRET_NAME` | prod | explicit secret name (overrides the convention) |
| `AWS_REGION` | prod | region for Secrets Manager (default `us-east-2`) |
| `VPN_GATEWAY` | local | FortiGate `host[:port]` (default port 443) |
| `VPN_USERNAME` / `VPN_PASSWORD` | local | VPN credentials |
| `VPN_TRUSTED_CERT` | both | FortiGate cert SHA256 digest (self-signed). *Required after first run — see below.* |
| `READY_FILE` | both | Readiness marker path (default `/shared/vpn-ready`) |
| `SSH_JUMP` / `SSH_KEY` / `SSH_FORWARDS` | both | optional SSH tunnels for `no_route` DBs |

## Readiness contract
Writes `$READY_FILE` (on the shared `/shared` volume) **only after** the tunnel is
up. The worker blocks until this file exists. `healthcheck.sh` is healthy only when
the marker exists and `ppp0` is up.

## Runtime requirements (set on the Pod / compose, not the image)
- capability **`NET_ADMIN`**
- device **`/dev/ppp`** (openfortivpn uses `pppd`)
- a shared volume mounted at **`/shared`** in both this and the worker container

> ⚠️ The host kernel must expose the **`ppp`** module. This is the highest-risk item
> for both local Docker (your Mac's VM) and the **AL2023 EKS node** — verify early.

## First run: discover the trusted cert
FortiGates usually use a self-signed cert. On the first dial with `VPN_TRUSTED_CERT`
empty, `openfortivpn` will refuse and print the expected digest:
```
... gateway certificate validation failed ...
... you can add 'trusted-cert <sha256>' ...
```
Copy that `<sha256>` into `VPN_TRUSTED_CERT` and redial.

## Build
```bash
docker build -t presa/vpn-sidecar:dev customer-integrators/v2/vpn-sidecar
```
