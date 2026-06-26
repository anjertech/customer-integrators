# worker — script-agnostic Python ETL runner with the Oracle thick-mode client.
#
# Waits for the vpn-sidecar's ready marker, fetches the per-tenant script + Oracle
# creds, then runs the script with those creds in its environment.
# Pinned to bookworm (Debian 12): trixie renamed libaio1 -> libaio1t64, and it
# matches the vpn-sidecar's debian:bookworm-slim.
FROM python:3.12-slim-bookworm

# Oracle Instant Client (thick mode) — the legacy DBs reject thin mode (DPY-3010).
# Override ORACLE_IC_URL at build time to pin a version or switch arch (arm64).
ARG ORACLE_IC_URL=https://download.oracle.com/otn_software/linux/instantclient/instantclient-basiclite-linuxx64.zip
ENV ORACLE_CLIENT_DIR=/opt/oracle/instantclient \
    PRESA_ORACLE_CLIENT_DIR=/opt/oracle/instantclient \
    LD_LIBRARY_PATH=/opt/oracle/instantclient \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends libaio1 unzip curl ca-certificates \
 && mkdir -p /opt/oracle \
 && curl -fsSL "$ORACLE_IC_URL" -o /tmp/ic.zip \
 && unzip -q /tmp/ic.zip -d /opt/oracle \
 && mv /opt/oracle/instantclient_* "$ORACLE_CLIENT_DIR" \
 && rm /tmp/ic.zip \
 && apt-get purge -y unzip curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY oracle_client.py entrypoint.py ./
RUN mkdir -p /scripts /shared

ENTRYPOINT ["python", "/app/entrypoint.py"]
