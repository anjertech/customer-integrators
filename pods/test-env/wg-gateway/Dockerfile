# WireGuard gateway — stands in for the client's FortiGate edge.
# Terminates the sidecar's tunnel on `vpn_transit` and forwards (NAT) into the
# `client_private` network, so private services are reachable ONLY through the VPN.
FROM --platform=linux/amd64 debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        wireguard-tools \
        iproute2 \
        iptables \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
