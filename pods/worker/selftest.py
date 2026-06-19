#!/usr/bin/env python3
"""Self-test: prove the worker image can initialize oracledb THICK mode.

This is the "runtime contract" check. It exercises only the image — the Oracle
Instant Client and oracledb — with no network, no SSH tunnel, and no database.
It is deliberately self-contained (it does NOT import the bind-mounted
oracle_client.py) so it can be run before any credentials or tunnel exist:

    docker compose run --rm worker --selftest

A pass means thick mode is correctly baked in; the only thing left for a live run
is the tunnel + credentials.
"""

import os
import sys

import oracledb


def main() -> int:
    lib_dir = os.environ.get("PRESA_ORACLE_CLIENT_DIR") or os.environ.get("ORACLE_CLIENT_DIR")
    if not lib_dir:
        print("✗ PRESA_ORACLE_CLIENT_DIR / ORACLE_CLIENT_DIR is not set", file=sys.stderr)
        return 1

    try:
        oracledb.init_oracle_client(lib_dir=lib_dir)
    except Exception as exc:  # noqa: BLE001 — surface whatever the client raises
        print(f"✗ thick-mode init failed from {lib_dir}: {exc}", file=sys.stderr)
        return 1

    if oracledb.is_thin_mode():
        print("✗ still in thin mode after init_oracle_client", file=sys.stderr)
        return 1

    version = ".".join(str(part) for part in oracledb.clientversion())
    print(f"✓ oracledb thick mode initialized (Instant Client {version}) from {lib_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
