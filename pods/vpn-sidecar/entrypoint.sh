#!/usr/bin/env bash
#
# PRESA vpn-sidecar entrypoint.
#
# Chain:  VPN (split-tunnel)  ->  SSH tunnel through the jump host
#
#   1. Dial the VPN and bring up a tunnel interface. The provider is pluggable via
#      VPN_PROVIDER:
#        - openfortivpn (default, production): FortiGate SSL-VPN, brings up ppp0.
#        - wireguard (local test env):         WireGuard, brings up wg0.
#      Either way we do NOT let the VPN install routes; we add ONLY the client's private
#      subnets ourselves (split tunnel) — the public path keeps the default route.
#   2. ssh (password auth, no shell) opens the local forwards the scripts hardcode:
#        16223 -> 192.168.10.88:6223   (Oracle Connection Manager / CMAN, SOURCE_ROUTE)
#        16224 -> 192.168.11.160:1521  (direct DB) ... etc.
#   3. Readiness = 127.0.0.1:<TUNNEL_READY_PORT> reachable (see healthcheck.sh).
#
# Required env: SSH_HOST, SSH_USER, SSH_PASSWORD, plus provider-specific creds (below).
# Optional: VPN_ROUTES, SSH_FORWARDS, VPN_PROVIDER (openfortivpn).
#
set -euo pipefail

log() { echo "[vpn-sidecar] $*"; }
die() { echo "[vpn-sidecar] ERROR: $*" >&2; exit 1; }

VPN_PROVIDER="${VPN_PROVIDER:-openfortivpn}"

# ---- credentials/endpoints common to every provider ----
: "${SSH_HOST:?SSH_HOST is required}"
: "${SSH_USER:?SSH_USER is required}"
: "${SSH_PASSWORD:?SSH_PASSWORD is required}"

# Split-tunnel: only these CIDRs route over the VPN.
VPN_ROUTES="${VPN_ROUTES:-192.168.10.0/24 192.168.11.0/24}"
# Exact local ports the scripts hardcode. Override only if the topology changes.
SSH_FORWARDS="${SSH_FORWARDS:-16223:192.168.10.88:6223 16224:192.168.11.160:1521 16225:192.168.11.173:1521 16226:192.168.10.85:1521}"

# Set by the dial_* functions:
VPN_IFACE=""    # the tunnel interface (ppp0 / wg0)
VPN_PID=""      # long-lived VPN process, if any (openfortivpn has one; wireguard does not)
SSH_PID=""
CONF=""         # openfortivpn temp config, if used

ensure_dev() {
  local path="$1" major="$2" minor="$3"
  if [[ ! -e "$path" ]]; then
    log "creating device $path"
    mkdir -p "$(dirname "$path")"
    mknod "$path" c "$major" "$minor" 2>/dev/null \
      || die "cannot create $path — the host needs the relevant kernel modules and the container needs CAP_MKNOD (run privileged)"
  fi
}

cleanup() {
  log "shutting down"
  [[ -n "$SSH_PID" ]] && kill "$SSH_PID" 2>/dev/null || true
  [[ -n "$VPN_PID" ]] && kill "$VPN_PID" 2>/dev/null || true
  [[ "$VPN_PROVIDER" == "wireguard" && -n "$VPN_IFACE" ]] && wg-quick down wg0 2>/dev/null || true
  [[ -n "$CONF" ]] && rm -f "$CONF" || true
}
trap cleanup EXIT INT TERM

# ---- provider: openfortivpn (FortiGate SSL-VPN) ----
dial_openfortivpn() {
  : "${VPN_GATEWAY_HOST:?VPN_GATEWAY_HOST is required}"
  : "${VPN_USERNAME:?VPN_USERNAME is required}"
  : "${VPN_PASSWORD:?VPN_PASSWORD is required}"
  local port="${VPN_GATEWAY_PORT:-443}"

  ensure_dev /dev/net/tun 10 200
  ensure_dev /dev/ppp     108 0

  CONF="$(mktemp)"; chmod 600 "$CONF"
  {
    echo "host = ${VPN_GATEWAY_HOST}"
    echo "port = ${port}"
    echo "username = ${VPN_USERNAME}"
    echo "password = ${VPN_PASSWORD}"
    echo "set-routes = 0"
    echo "set-dns = 0"
    [[ -n "${VPN_TRUSTED_CERT:-}" ]] && echo "trusted-cert = ${VPN_TRUSTED_CERT}"
  } > "$CONF"

  log "dialing FortiGate ${VPN_GATEWAY_HOST}:${port} as ${VPN_USERNAME} (split-tunnel)"
  openfortivpn -c "$CONF" &
  VPN_PID=$!

  for _ in $(seq 1 60); do
    VPN_IFACE="$(ip -o link show 2>/dev/null | awk -F': ' '/ ppp[0-9]+/{print $2; exit}')"
    [[ -n "$VPN_IFACE" ]] && break
    kill -0 "$VPN_PID" 2>/dev/null || die "openfortivpn exited before the tunnel came up (check creds / VPN_TRUSTED_CERT / gateway reachability)"
    sleep 1
  done
  [[ -n "$VPN_IFACE" ]] || die "VPN interface did not appear within 60s"
}

# ---- provider: wireguard (local test env) ----
dial_wireguard() {
  : "${WG_CLIENT_PRIVATE_KEY:?WG_CLIENT_PRIVATE_KEY is required}"
  : "${WG_SERVER_PUBLIC_KEY:?WG_SERVER_PUBLIC_KEY is required}"
  : "${WG_ENDPOINT:?WG_ENDPOINT is required (host:port of the wireguard gateway)}"
  local address="${WG_CLIENT_ADDRESS:-10.13.13.2/24}"
  local allowed="${WG_ALLOWED_IPS:-192.168.0.0/16}"

  ensure_dev /dev/net/tun 10 200

  mkdir -p /etc/wireguard
  # Table = off: don't let wg-quick add routes — we add only the split-tunnel subnets
  # ourselves below, exactly like the openfortivpn path.
  cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
PrivateKey = ${WG_CLIENT_PRIVATE_KEY}
Address = ${address}
Table = off

[Peer]
PublicKey = ${WG_SERVER_PUBLIC_KEY}
Endpoint = ${WG_ENDPOINT}
AllowedIPs = ${allowed}
PersistentKeepalive = 25
EOF
  chmod 600 /etc/wireguard/wg0.conf

  log "dialing WireGuard gateway ${WG_ENDPOINT} (split-tunnel)"
  wg-quick up wg0
  VPN_IFACE="wg0"
  # No long-lived process: the wireguard tunnel lives in the kernel.
  ip link show wg0 >/dev/null 2>&1 || die "wg0 did not come up"
}

# ---- 1. dial the VPN (provider-specific) ----
case "$VPN_PROVIDER" in
  openfortivpn) dial_openfortivpn ;;
  wireguard)    dial_wireguard ;;
  *) die "unknown VPN_PROVIDER '${VPN_PROVIDER}' (expected openfortivpn|wireguard)" ;;
esac
log "VPN up on ${VPN_IFACE} (provider=${VPN_PROVIDER})"

# ---- 2. split-tunnel routes: only the client's private subnets ----
for cidr in $VPN_ROUTES; do
  log "route ${cidr} -> ${VPN_IFACE}"
  ip route replace "$cidr" dev "$VPN_IFACE" || die "failed to add route ${cidr}"
done

# ---- 3. SSH tunnel through the jump host ----
declare -a L_ARGS=()
for fwd in $SSH_FORWARDS; do
  L_ARGS+=("-L" "$fwd")
done

log "opening SSH tunnel ${SSH_USER}@${SSH_HOST} with forwards: ${SSH_FORWARDS}"
export SSHPASS="$SSH_PASSWORD"           # sshpass -e reads the password from here
sshpass -e ssh \
  -o PubkeyAuthentication=no \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -N "${L_ARGS[@]}" "${SSH_USER}@${SSH_HOST}" &
SSH_PID=$!

log "tunnel established; readiness = 127.0.0.1:${TUNNEL_READY_PORT:-16223} (see healthcheck)"

# ---- supervise: if the SSH tunnel (or the VPN process, if any) exits, tear down + fail ----
wait -n ${VPN_PID:+"$VPN_PID"} "$SSH_PID" || true
die "a tunnel process exited — bringing the sidecar down"
