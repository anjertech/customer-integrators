# scripts

Per-tenant ETL scripts the **worker** runs. The worker fetches one of these (from
S3 in production, or mounted locally), injects the Oracle connection as `ORACLE_*`
env vars, and runs it. Scripts are plain Python and may `import oracle_client`
(baked into the worker image) to start thick mode.

- **`test_oracle_connection.py`** — the connectivity smoke test (`SELECT 1 FROM DUAL`).
  Run this first to prove the VPN → SSH → Oracle chain before any real ETL.

A script "passes" by printing its success output and exiting `0`; any failure must
exit non-zero so the worker/Job is marked failed.
