# vpn-sidecar — dials the client's FortiGate via openfortivpn, then signals
# "ready" on a shared volume so the worker can connect.
#
# Self-fetches its per-tenant VPN config from AWS Secrets Manager (via the pod's
# Pod Identity) — so it carries awscli + jq.
#
# Runtime requirements (set on the Pod / in docker-compose, NOT here):
#   - capability NET_ADMIN
#   - device     /dev/ppp        (openfortivpn uses pppd)
#   - the SAME shared volume mounted at /shared in this AND the worker container
FROM debian:bookworm-slim

# x86_64 by default (EKS target); override for arm64 with awscli-exe-linux-aarch64.zip
ARG AWSCLI_URL=https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openfortivpn \
      ppp \
      openssh-client \
      sshpass \
      iproute2 \
      iputils-ping \
      ca-certificates \
      procps \
      curl \
      unzip \
      jq \
 && curl -fsSL "$AWSCLI_URL" -o /tmp/awscliv2.zip \
 && unzip -q /tmp/awscliv2.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/aws /tmp/awscliv2.zip \
 && apt-get purge -y unzip \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh healthcheck.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.sh

ENV READY_FILE=/shared/vpn-ready

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
  CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
