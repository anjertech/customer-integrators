#!/usr/bin/env python3
"""ETL connectivity smoke test — SELECT 1 FROM DUAL.

Proves the whole chain end-to-end: the worker reached the Oracle DB (through the
vpn-sidecar's VPN / SSH tunnel) and can run a query. Print the success line + exit
0 ⇒ connectivity works. This is the ETL equivalent of the nginx/ALB smoke test.

Connection comes from env (injected by the worker from Secrets Manager or, locally,
passed directly):
  ORACLE_HOST              (required)
  ORACLE_PORT              (default 1521)
  ORACLE_SERVICE  or  ORACLE_SID   (one required)
  ORACLE_USER, ORACLE_PASSWORD     (required)
"""

import os
import sys

import oracledb

from oracle_client import initialize_oracle_thick_mode


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        print(f"[test] ✗ missing required env var {name}", flush=True)
        sys.exit(2)
    return val


def main() -> None:
    host = env("ORACLE_HOST", required=True)
    port = int(env("ORACLE_PORT", "1521"))
    service = env("ORACLE_SERVICE")
    sid = env("ORACLE_SID")
    user = env("ORACLE_USER", required=True)
    password = env("ORACLE_PASSWORD", required=True)

    if not (service or sid):
        print("[test] ✗ need ORACLE_SERVICE or ORACLE_SID", flush=True)
        sys.exit(2)

    print("[test] initializing Oracle thick mode...", flush=True)
    client_dir = initialize_oracle_thick_mode()
    print(f"[test] thick mode ready ({client_dir})", flush=True)

    dsn = (
        oracledb.makedsn(host, port, service_name=service)
        if service
        else oracledb.makedsn(host, port, sid=sid)
    )
    target = service or sid
    print(f"[test] connecting to {user}@{host}:{port}/{target} ...", flush=True)

    try:
        with oracledb.connect(user=user, password=password, dsn=dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
                (result,) = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 — surface any failure as a clear non-zero exit
        print(f"[test] ✗ connection/query failed: {exc}", flush=True)
        sys.exit(1)

    print("[test] ✓ Connected successfully!", flush=True)
    print(f"[test] ✓ Test query (SELECT 1 FROM DUAL): {result}", flush=True)

    if result != 1:
        print(f"[test] ✗ unexpected result: {result}", flush=True)
        sys.exit(1)

    print("[test] ✓ connectivity smoke test passed", flush=True)


if __name__ == "__main__":
    main()
