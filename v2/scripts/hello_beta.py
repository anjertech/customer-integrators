#!/usr/bin/env python3
"""Simple per-tenant test script: greet, then run SELECT 1."""
import os

import oracledb

from oracle_client import initialize_oracle_thick_mode

SCRIPT = "beta"
tenant = os.environ.get("TENANT_ID", "unknown")
print(f"hello from {tenant} (script: {SCRIPT})", flush=True)

initialize_oracle_thick_mode()
port = int(os.environ.get("ORACLE_PORT", "1521"))
service = os.environ.get("ORACLE_SERVICE")
dsn = (
    oracledb.makedsn(os.environ["ORACLE_HOST"], port, service_name=service)
    if service
    else oracledb.makedsn(os.environ["ORACLE_HOST"], port, sid=os.environ.get("ORACLE_SID"))
)
with oracledb.connect(user=os.environ["ORACLE_USER"], password=os.environ["ORACLE_PASSWORD"], dsn=dsn) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM DUAL")
        (result,) = cur.fetchone()
print(f"[{tenant}] ✓ SELECT 1 FROM DUAL = {result}", flush=True)
