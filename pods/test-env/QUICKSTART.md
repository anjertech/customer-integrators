# PRESA test-env — Quickstart

A local simulation of a tenant's network, used to test the real PRESA **worker** +
**vpn-sidecar** end-to-end — no external client, no real VPN, no cloud. Run it from inside
the `customer-integrators` repo (it builds the worker/vpn-sidecar images from `../` and
mounts the scripts from the repo root).

It brings up, all as local containers:
- a mock **Oracle** DB (`SISTEMAS`) on a private network,
- a mock **SSH jump host**,
- a **WireGuard gateway** (stands in for the client's FortiGate),
- the real **vpn-sidecar** (dials the VPN + opens the SSH tunnel), and
- the real **worker** (runs `test_oracle_connection.py` through the tunnel).

Success = the worker connects through VPN → SSH → Oracle and prints `SELECT 1 FROM DUAL: 1`.

## Run it

Requires Docker (Desktop or Engine) with `linux/amd64` support.

```bash
cp .env.example .env

# 1. bring up the mock client + the vpn-sidecar (builds images first time, ~1–2 min)
docker compose -f docker-compose.test.yml up -d --build

# 2. run the worker — dials the tunnel, runs the script, prints the result
docker compose -f docker-compose.test.yml up worker
```

Expected output from the worker:
```
✓ Connected successfully!
✓ Test query (SELECT 1 FROM DUAL): 1
Passed: 1/1
```

## Inspect / tear down
```bash
docker compose -f docker-compose.test.yml ps                  # all healthy?
docker compose -f docker-compose.test.yml logs -f vpn-sidecar # tunnel setup
docker compose -f docker-compose.test.yml logs -f worker      # the script run

docker compose -f docker-compose.test.yml down                # stop (add -v to wipe Oracle data)
```

## What's in here
- `docker-compose.test.yml` — the whole stack (5 services, 2 networks).
- `mock-jump/`, `wg-gateway/`, `mock-cman/` — the simulated client infrastructure.
- `.env.example` — throwaway mock creds + WireGuard keys; copy to `.env`.

The REAL images under test are built from elsewhere in the repo:
- `../vpn-sidecar/`, `../worker/` — the worker + sidecar images.
- `../../test_oracle_connection.py`, `../../oracle_client.py` — the unmodified script the worker runs.

> All credentials/keys here are **throwaway mock values** for the local sim — not real secrets.
