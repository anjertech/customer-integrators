#!/usr/bin/env bash
#
# Dial the client's FortiGate via openfortivpn, optionally open SSH tunnels for
# no_route databases, then write the readiness marker so the worker can start.
# Stays alive while the VPN is up; exits non-zero if the tunnel fails or drops.
#
# Two modes (same as the worker):
#   - production: TENANT_ID set → self-fetch the VPN config from Secrets Manager
#                 (secret presa/etl/<TENANT_ID>, or SECRET_NAME) via Pod Identity
#   - local test: VPN_GATEWAY/USERNAME/PASSWORD provided via env → no AWS needed
set -euo pipefail

# ---- production: self-fetch the VPN config from Secrets Manager ---------------
# Skipped when VPN_GATEWAY is already set (local docker-compose testing).
SECRET_NAME="${SECRET_NAME:-${TENANT_ID:+presa/etl/${TENANT_ID}}}"
if [ -z "${VPN_GATEWAY:-}" ] && [ -n "${SECRET_NAME:-}" ]; then
  export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-2}"
  echo "[sidecar] fetching VPN config from Secrets Manager: ${SECRET_NAME}"
  secret_json="$(aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" --query SecretString --output text)"
  export VPN_GATEWAY="$(jq -r '.vpn.gateway' <<<"$secret_json")"
  export VPN_USERNAME="$(jq -r '.vpn.username' <<<"$secret_json")"
  export VPN_PASSWORD="$(jq -r '.vpn.password' <<<"$secret_json")"
  export VPN_TRUSTED_CERT="$(jq -r '.vpn.trusted_cert // empty' <<<"$secret_json")"
  export SSH_JUMP="$(jq -r '.ssh.jump // empty' <<<"$secret_json")"
  export SSH_FORWARDS="$(jq -r '.ssh.forwards // empty' <<<"$secret_json")"
  export SSH_PASSWORD="$(jq -r '.ssh.password // empty' <<<"$secret_json")"
  export SSH_PORT="$(jq -r '.ssh.port // empty' <<<"$secret_json")"
  ssh_key="$(jq -r '.ssh.private_key // empty' <<<"$secret_json")"
  if [ -n "$ssh_key" ]; then
    printf '%s\n' "$ssh_key" >/tmp/ssh_key
    chmod 600 /tmp/ssh_key
    export SSH_KEY=/tmp/ssh_key
  fi
fi

# ---- config (from env, or just-fetched above) --------------------------------
: "${VPN_GATEWAY:?required: host[:port] of the FortiGate, e.g. vpn.client.com:443}"
: "${VPN_USERNAME:?required}"
# VPN_PASSWORD is optional: some SSL-VPN setups authenticate without a stored
# password (or prompt at connect). Left empty, we still dial so the gateway's own
# response tells us what it wants — instead of failing our precheck first.
VPN_PASSWORD="${VPN_PASSWORD:-}"
[ -z "$VPN_PASSWORD" ] && echo "[sidecar] ⚠ VPN_PASSWORD empty — attempting passwordless auth"
VPN_TRUSTED_CERT="${VPN_TRUSTED_CERT:-}"
READY_FILE="${READY_FILE:-/shared/vpn-ready}"
SSH_JUMP="${SSH_JUMP:-}"
SSH_KEY="${SSH_KEY:-}"
SSH_FORWARDS="${SSH_FORWARDS:-}"
SSH_PASSWORD="${SSH_PASSWORD:-}"
SSH_PORT="${SSH_PORT:-}"

host="${VPN_GATEWAY%%:*}"
port="${VPN_GATEWAY##*:}"
[ "$port" = "$host" ] && port=443

# ---- openfortivpn config file (keeps the password out of `ps`) ---------------
conf="$(mktemp)"
chmod 600 "$conf"
{
  echo "host = $host"
  echo "port = $port"
  echo "username = $VPN_USERNAME"
  echo "password = $VPN_PASSWORD"
  [ -n "$VPN_TRUSTED_CERT" ] && echo "trusted-cert = $VPN_TRUSTED_CERT"
} >"$conf"

vpn_pid=""
extra_pids=()
cleanup() {
  rm -f "$READY_FILE" "$conf"
  [ -n "$vpn_pid" ] && kill "$vpn_pid" 2>/dev/null || true
  for p in "${extra_pids[@]:-}"; do kill "$p" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

mkdir -p "$(dirname "$READY_FILE")"
rm -f "$READY_FILE"

# ---- dial --------------------------------------------------------------------
echo "[sidecar] dialing openfortivpn → ${host}:${port}"
# </dev/null: if the gateway prompts for a password (e.g. passwordless attempt that
# it rejects), openfortivpn gets EOF and fails fast instead of hanging on a TTY.
openfortivpn -c "$conf" </dev/null >/tmp/vpn.log 2>&1 &
vpn_pid=$!

# ---- wait for the tunnel -----------------------------------------------------
echo "[sidecar] waiting for tunnel (up to 60s)..."
for _ in $(seq 1 60); do
  kill -0 "$vpn_pid" 2>/dev/null || {
    echo "[sidecar] openfortivpn exited early:"
    cat /tmp/vpn.log
    exit 1
  }
  grep -q "Tunnel is up and running" /tmp/vpn.log && break
  sleep 1
done
if ! grep -q "Tunnel is up and running" /tmp/vpn.log; then
  echo "[sidecar] tunnel did not come up in time:"
  cat /tmp/vpn.log
  exit 1
fi
echo "[sidecar] ✓ VPN tunnel up"

# ---- optional SSH tunnels for no_route DBs -----------------------------------
if [ -n "$SSH_FORWARDS" ]; then
  [ -n "$SSH_JUMP" ] || {
    echo "[sidecar] SSH_FORWARDS set but SSH_JUMP missing"
    exit 1
  }
  ssh_args=(-N -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes)
  [ -n "$SSH_PORT" ] && ssh_args+=(-p "$SSH_PORT")
  IFS=',' read -ra _fwds <<<"$SSH_FORWARDS"
  for f in "${_fwds[@]}"; do ssh_args+=(-L "$f"); done

  if [ -n "$SSH_PASSWORD" ]; then
    # password auth: the client disables pubkey (PubkeyAuthentication=no); sshpass
    # feeds the password via the SSHPASS env var so it never lands in `ps`.
    ssh_args+=(-o PubkeyAuthentication=no)
    echo "[sidecar] opening SSH tunnels (password auth) via ${SSH_JUMP}: ${SSH_FORWARDS}"
    SSHPASS="$SSH_PASSWORD" sshpass -e ssh "${ssh_args[@]}" "$SSH_JUMP" </dev/null &
  else
    [ -n "$SSH_KEY" ] && ssh_args+=(-i "$SSH_KEY")
    echo "[sidecar] opening SSH tunnels (key auth) via ${SSH_JUMP}: ${SSH_FORWARDS}"
    ssh "${ssh_args[@]}" "$SSH_JUMP" </dev/null &
  fi
  ssh_pid=$!
  extra_pids+=("$ssh_pid")

  # Wait for the local forward ports to actually accept connections. ssh binds them
  # only AFTER host-key + auth complete, so a blind sleep races — the readiness
  # marker would be written before the tunnels listen ("connection refused").
  ssh_deadline=$((SECONDS + 30))
  IFS=',' read -ra _wait_fwds <<<"$SSH_FORWARDS"
  for f in "${_wait_fwds[@]}"; do
    lport="${f%%:*}"
    until (exec 3<>"/dev/tcp/127.0.0.1/${lport}") 2>/dev/null; do
      kill -0 "$ssh_pid" 2>/dev/null || {
        echo "[sidecar] ✗ SSH tunnel process died (check SSH_PASSWORD / SSH_JUMP / SSH_FORWARDS)"
        exit 1
      }
      [ "$SECONDS" -ge "$ssh_deadline" ] && {
        echo "[sidecar] ✗ SSH forward :${lport} not listening after 30s"
        exit 1
      }
      sleep 1
    done
    exec 3>&- 2>/dev/null || true
    echo "[sidecar] ✓ SSH forward :${lport} up"
  done
  echo "[sidecar] ✓ SSH tunnels up"
fi

# ---- signal readiness + surface the VPN log ----------------------------------
touch "$READY_FILE"
echo "[sidecar] ✓ ready — wrote ${READY_FILE}"
tail -f /tmp/vpn.log &
extra_pids+=($!)

wait "$vpn_pid"
echo "[sidecar] openfortivpn exited — sidecar shutting down"
exit 1
