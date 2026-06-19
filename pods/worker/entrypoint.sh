#!/usr/bin/env bash
#
# PRESA worker entrypoint — script-agnostic runner.
#
# Runtime contract (see ../README.md):
#   - oracledb + Oracle Instant Client (thick mode) are baked into the image, and
#     PRESA_ORACLE_CLIENT_DIR points oracle_client.py at the client.
#   - The script and its helpers (e.g. oracle_client.py) are provided at runtime
#     under /scripts (bind-mounted, read-only). The image makes NO assumption about
#     the script's internals, imports, or file count.
#   - The SSH tunnel (CMAN on 127.0.0.1:16223 + direct DB forwards 16224/16225/16226)
#     is created by the vpn-sidecar in the SHARED network namespace; we wait for it
#     to be reachable before running the script.
#   - The Oracle password is read by the script from ORACLE_PASSWORD (no interactive
#     getpass prompt). The script's --user defaults to PRESA.
#
# Args:
#   --tenant <id>     tenant identifier (logging / future per-tenant config)
#   --script <path>   path to the script to run (e.g. /scripts/test_oracle_connection.py)
#   --selftest        prove thick-mode init only (no tunnel wait, no DB) and exit
#   <anything else>   forwarded verbatim to the script
#
set -euo pipefail

log() { echo "[worker] $*"; }

# Readiness gate: block until the sidecar's CMAN forward is reachable. This is
# belt-and-suspenders alongside compose's `depends_on: service_healthy`, and makes
# the container correct when run standalone too.
wait_for_tunnel() {
  local host="${TUNNEL_READY_HOST:-127.0.0.1}"
  local port="${TUNNEL_READY_PORT:-16223}"
  local timeout="${TUNNEL_READY_TIMEOUT:-120}"
  local deadline=$(( SECONDS + timeout ))

  log "waiting for tunnel ${host}:${port} (timeout ${timeout}s)"
  until (exec 3<>"/dev/tcp/${host}/${port}") 2>/dev/null; do
    if (( SECONDS >= deadline )); then
      log "ERROR: tunnel ${host}:${port} not reachable after ${timeout}s"
      return 1
    fi
    sleep 2
  done
  exec 3>&- 2>/dev/null || true
  log "tunnel ${host}:${port} is reachable"
}

TENANT=""
SCRIPT=""
SELFTEST=0
declare -a EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tenant)   TENANT="${2:?--tenant needs a value}"; shift 2 ;;
    --script)   SCRIPT="${2:?--script needs a value}"; shift 2 ;;
    --selftest) SELFTEST=1; shift ;;
    --)         shift; EXTRA+=("$@"); break ;;
    *)          EXTRA+=("$1"); shift ;;
  esac
done

if [[ "$SELFTEST" -eq 1 ]]; then
  log "running thick-mode self-test (no tunnel, no DB)"
  exec python /usr/local/bin/selftest.py
fi

[[ -n "$SCRIPT" ]] || { log "ERROR: --script <path> is required"; exit 2; }
[[ -f "$SCRIPT" ]] || { log "ERROR: script not found: $SCRIPT"; exit 2; }

log "tenant=${TENANT:-<none>} script=${SCRIPT}"
log "Oracle Instant Client: ${PRESA_ORACLE_CLIENT_DIR:-<unset>}"

if [[ "${WAIT_FOR_TUNNEL:-1}" == "1" ]]; then
  wait_for_tunnel
fi

# The script imports its helpers (e.g. `from oracle_client import ...`) from its own
# directory. Running `python <path>` already puts that dir on sys.path[0]; exporting
# PYTHONPATH as well keeps imports working no matter how the script is invoked.
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"

log "exec: python ${SCRIPT} ${EXTRA[*]:-}"
exec python "$SCRIPT" "${EXTRA[@]}"
