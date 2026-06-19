# Mock SSH jump host — stands in for PRESA@192.168.10.83.
# Password auth (the sidecar uses PubkeyAuthentication=no + sshpass) and TCP forwarding
# enabled so the worker's `ssh -L 16223:192.168.10.88:6223 ...` can reach CMAN.
FROM --platform=linux/amd64 debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
