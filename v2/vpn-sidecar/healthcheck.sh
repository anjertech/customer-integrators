#!/usr/bin/env bash
# Healthy only when the readiness marker exists AND the ppp interface is up.
set -euo pipefail
READY_FILE="${READY_FILE:-/shared/vpn-ready}"
[ -f "$READY_FILE" ] && ip link show ppp0 >/dev/null 2>&1
