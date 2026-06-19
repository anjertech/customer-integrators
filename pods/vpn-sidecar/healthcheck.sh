#!/usr/bin/env bash
#
# Readiness probe for the vpn-sidecar. Passes once the CMAN forward is reachable,
# which is exactly what the worker (and test_oracle_connection.py) connect to. The
# worker's `depends_on: condition: service_healthy` is gated on this.
set -euo pipefail
exec nc -z 127.0.0.1 "${TUNNEL_READY_PORT:-16223}"
