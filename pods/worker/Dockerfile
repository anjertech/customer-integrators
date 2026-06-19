# PRESA worker — unprivileged, script-agnostic ETL runtime.
#
# The image provides the RUNTIME (Python + oracledb + Oracle Instant Client thick
# mode + common libs); scripts bring only LOGIC and are supplied at runtime.
#
# linux/amd64 only: Oracle thick mode is mandatory for the legacy DB servers
# (thin mode fails with DPY-3010), and the Instant Client is amd64.
FROM --platform=linux/amd64 python:3.12-slim-bookworm

# OS deps: libaio is required by the Instant Client thick-mode libraries;
# curl/unzip are used only to fetch and unpack the client at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libaio1 \
        ca-certificates \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# --- Oracle Instant Client (Basic Light, latest 23.x, linux x64) ---------------
# The "-linuxx64.zip" links always resolve to the latest released 23.x build.
# Basic Light is the smaller variant; thick mode works with it. The unpacked dir
# is named instantclient_23_<n>; we symlink it to a stable path so oracle_client.py
# can find it via PRESA_ORACLE_CLIENT_DIR regardless of the dot release.
ARG INSTANTCLIENT_URL="https://download.oracle.com/otn_software/linux/instantclient/instantclient-basiclite-linuxx64.zip"
ENV PRESA_ORACLE_CLIENT_DIR=/opt/oracle/instantclient
RUN mkdir -p /opt/oracle \
    && curl -fsSL "$INSTANTCLIENT_URL" -o /tmp/instantclient.zip \
    && unzip -q /tmp/instantclient.zip -d /opt/oracle \
    && rm /tmp/instantclient.zip \
    && ln -s /opt/oracle/instantclient_* "$PRESA_ORACLE_CLIENT_DIR" \
    && echo "$PRESA_ORACLE_CLIENT_DIR" > /etc/ld.so.conf.d/oracle-instantclient.conf \
    && ldconfig

# --- Python runtime libraries --------------------------------------------------
# Baked broadly so any tenant script runs without per-script installs:
#   oracledb (DB), requests + aiohttp (API POST path), boto3 (S3 script sync on EKS).
RUN pip install --no-cache-dir \
        "oracledb>=2.0" \
        requests \
        aiohttp \
        boto3

ENV PYTHONUNBUFFERED=1

# Unprivileged runtime user — the worker never needs root.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin worker
WORKDIR /home/worker/app

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY selftest.py   /usr/local/bin/selftest.py
RUN chmod +x /usr/local/bin/entrypoint.sh

USER 10001
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Per-run args (--tenant / --script) are supplied by docker-compose.
