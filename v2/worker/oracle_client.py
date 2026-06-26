"""Oracle Instant Client (thick-mode) bootstrap.

The legacy client Oracle servers reject python-oracledb's default *thin* mode
(DPY-3010), so scripts must initialize thick mode against an Instant Client.
In the worker image the client lives at a fixed path exposed via
PRESA_ORACLE_CLIENT_DIR (set in the Dockerfile).
"""

import os

import oracledb


def initialize_oracle_thick_mode() -> str:
    """Initialize thick mode if not already done. Returns the client dir used."""
    if not oracledb.is_thin_mode():
        return "already initialized"

    lib_dir = os.environ.get("PRESA_ORACLE_CLIENT_DIR") or os.environ.get("ORACLE_CLIENT_DIR")
    # lib_dir=None falls back to the default loader path (LD_LIBRARY_PATH).
    oracledb.init_oracle_client(lib_dir=lib_dir or None)
    return lib_dir or "(default loader path)"
