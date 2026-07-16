#!/usr/bin/env python3
"""SQL Server (ODBC/pyodbc) SELECT 1 smoke test — for the universidad/mxa integrator.

The worker image already ships pyodbc + msodbcsql18, so no image change is needed.
Proves the worker reached the SQL Server (through the VPN, no SSH tunnel) and can run
a query. Connect with either a full ODBC connection string or discrete parts.

Env — provide EITHER the full string:
  ODBC_CONNECTION_STRING / UNIVERSIDAD_ODBC_CONNECTION_STRING   full pyodbc string
OR the parts:
  MSSQL_HOST (required), MSSQL_PORT (default 1433), MSSQL_DATABASE,
  MSSQL_USER, MSSQL_PASSWORD,
  MSSQL_DRIVER (default "ODBC Driver 18 for SQL Server"),
  MSSQL_ENCRYPT (default "no"), MSSQL_TRUST_CERT (default "yes"),
  MSSQL_TIMEOUT (default 15)
"""

import os
import re
import sys


def log(msg: str) -> None:
    print(f"[mssql] {msg}", flush=True)


def build_connection_string() -> str:
    cs = os.environ.get("ODBC_CONNECTION_STRING") or os.environ.get(
        "UNIVERSIDAD_ODBC_CONNECTION_STRING"
    )
    if cs:
        return cs

    host = os.environ.get("MSSQL_HOST")
    if not host:
        log("✗ set ODBC_CONNECTION_STRING (or MSSQL_HOST + parts)")
        sys.exit(2)

    driver = os.environ.get("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server")
    port = os.environ.get("MSSQL_PORT", "1433")
    parts = [f"DRIVER={{{driver}}}", f"SERVER={host},{port}"]
    if os.environ.get("MSSQL_DATABASE"):
        parts.append(f"DATABASE={os.environ['MSSQL_DATABASE']}")
    if os.environ.get("MSSQL_USER"):
        parts.append(f"UID={os.environ['MSSQL_USER']}")
    if os.environ.get("MSSQL_PASSWORD") is not None:
        parts.append(f"PWD={os.environ.get('MSSQL_PASSWORD', '')}")
    parts.append(f"Encrypt={os.environ.get('MSSQL_ENCRYPT', 'no')}")
    parts.append(f"TrustServerCertificate={os.environ.get('MSSQL_TRUST_CERT', 'yes')}")
    return ";".join(parts)


def redact(cs: str) -> str:
    return re.sub(r"(PWD=)[^;]*", r"\1[REDACTED]", cs, flags=re.IGNORECASE)


def main() -> None:
    import pyodbc

    cs = build_connection_string()
    timeout = int(os.environ.get("MSSQL_TIMEOUT", "15"))
    log(f"drivers available: {pyodbc.drivers()}")
    log(f"connection string: {redact(cs)}")
    log("connecting...")
    try:
        conn = pyodbc.connect(cs, timeout=timeout)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        (result,) = cur.fetchone()
        conn.close()
    except Exception as exc:  # noqa: BLE001 — surface any failure as a clear non-zero exit
        log(f"✗ connection/query failed: {exc}")
        sys.exit(1)

    log(f"✓ SELECT 1 = {result}")
    if result != 1:
        sys.exit(1)
    log("✓ SQL Server smoke test passed")


if __name__ == "__main__":
    main()
