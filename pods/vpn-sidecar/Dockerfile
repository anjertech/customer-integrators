# PRESA vpn-sidecar — brings up the network for the worker.
#
# Responsibilities:
#   1. Dial the tenant's FortiGate SSL-VPN with openfortivpn (user/pass), SPLIT-TUNNEL.
#   2. Open the SSH tunnel through the jump host (password auth via sshpass), forwarding
#      the exact local ports the scripts hardcode.
#   3. Expose a healthcheck (CMAN forward reachable) used as the worker's readiness gate.
#
# Privileged by design: needs NET_ADMIN + /dev/net/tun (and pppd's /dev/ppp) to bring
# up the tunnel. It never touches tenant DB data — that isolation is the whole point of
# splitting the VPN tooling out of the worker image.
#
# linux/amd64 to match the worker.
FROM --platform=linux/amd64 debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openfortivpn \
        openssh-client \
        sshpass \
        ppp \
        wireguard-tools \
        iproute2 \
        netcat-openbsd \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh  /usr/local/bin/entrypoint.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.sh

# Runs as root by design (tunnel setup needs NET_ADMIN + tun/ppp devices).
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
