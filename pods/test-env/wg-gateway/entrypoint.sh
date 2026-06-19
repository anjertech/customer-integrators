#!/usr/bin/env bash
#
# WireGuard gateway: bring up the server interface, then NAT/forward tunnel traffic into
# the client_private network so the sidecar (once connected + routed) can reach the
# private services exactly as it would reach a real client's internal subnets.
set -euo pipefail

log() { echo "[wg-gateway] $*"; }
die() { echo "[wg-gateway] ERROR: $*" >&2; exit 1; }

: "${WG_SERVER_PRIVATE_KEY:?WG_SERVER_PRIVATE_KEY is required}"
: "${WG_CLIENT_PUBLIC_KEY:?WG_CLIENT_PUBLIC_KEY is required}"

WG_ADDRESS="${WG_SERVER_ADDRESS:-10.13.13.1/24}"
WG_PORT="${WG_LISTEN_PORT:-51820}"
WG_CLIENT_ALLOWED="${WG_CLIENT_ALLOWED:-10.13.13.2/32}"
PRIVATE_CIDR="${PRIVATE_CIDR:-192.168.0.0/16}"

# /dev/net/tun is required for the wireguard interface.
if [[ ! -e /dev/net/tun ]]; then
  mkdir -p /dev/net
  mknod /dev/net/tun c 10 200 2>/dev/null || die "cannot create /dev/net/tun (need CAP_MKNOD/privileged)"
fi

mkdir -p /etc/wireguard
cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = ${WG_ADDRESS}
ListenPort = ${WG_PORT}
PrivateKey = ${WG_SERVER_PRIVATE_KEY}

[Peer]
PublicKey = ${WG_CLIENT_PUBLIC_KEY}
AllowedIPs = ${WG_CLIENT_ALLOWED}
EOF
chmod 600 /etc/wireguard/wg0.conf

cleanup() { wg-quick down wg0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

log "bringing up wireguard server (wg0, listen ${WG_PORT})"
wg-quick up wg0

# Forward + NAT: traffic arriving over the tunnel and destined for the private network is
# masqueraded behind the gateway's client_private IP, so replies come back to the gateway
# (and then back over the tunnel). ip_forward is also set via compose sysctls.
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
iptables -t nat -A POSTROUTING -d "${PRIVATE_CIDR}" -j MASQUERADE || die "MASQUERADE rule failed (need NET_ADMIN)"
iptables -A FORWARD -i wg0 -j ACCEPT || true
iptables -A FORWARD -o wg0 -j ACCEPT || true

log "ready: tunnel up, NAT to ${PRIVATE_CIDR} enabled"
wg show

# Stay alive for the life of the container.
sleep infinity &
wait
