#!/usr/bin/env python3
"""PRESA ETL worker — script-agnostic runner.

Flow:
  1. wait for the vpn-sidecar's readiness marker (so the tunnel is up)
  2. resolve the tenant's script + Oracle credentials
  3. run the script with the creds in its environment; exit with its exit code

Two modes:
  - production:  --tenant <id>   → derive everything from the id:
        * tenant entry from tenants.json (TENANTS_S3) → its script
        * Oracle creds from Secrets Manager (secret name = the entry's `secret`,
          or by convention `presa/etl/<id>`)
      AWS access comes from the pod's (shared) `worker` Pod Identity role.
  - local test:  no --tenant     → use env directly:
        SCRIPT_PATH (mounted) + ORACLE_* ; set WAIT_FOR_VPN=false to skip the VPN.
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time


def log(msg: str) -> None:
    print(f"[worker] {msg}", flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", help="tenant id; derive script + secret from it (production mode)")
    return p.parse_args()


def wait_for_vpn(ready_file: str, timeout: int) -> None:
    log(f"waiting for VPN ready marker {ready_file} (up to {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pathlib.Path(ready_file).exists():
            log("✓ VPN ready")
            return
        time.sleep(2)
    log(f"✗ VPN not ready after {timeout}s — is the sidecar up?")
    sys.exit(1)


def _s3_get(uri: str) -> bytes:
    import boto3

    bucket, key = uri.removeprefix("s3://").split("/", 1)
    return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()


def load_tenant_entry(tenant_id: str) -> dict:
    """Find the tenant's entry in tenants.json (S3), keyed by id."""
    uri = os.environ.get("TENANTS_S3")
    if not uri:
        log("✗ --tenant requires TENANTS_S3 (s3://bucket/tenants.json)")
        sys.exit(2)
    data = json.loads(_s3_get(uri))
    for t in data.get("tenants", []):
        if t.get("id") == tenant_id:
            return t
    log(f"✗ tenant '{tenant_id}' not found in {uri}")
    sys.exit(2)


def fetch_script_from_s3(uri: str, dest: str) -> None:
    log(f"fetching script from {uri}")
    pathlib.Path(dest).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(dest).write_bytes(_s3_get(uri))


def fetch_oracle_creds(secret_name: str, region: str) -> dict:
    import boto3

    log(f"fetching Oracle creds from Secrets Manager: {secret_name}")
    sm = boto3.client("secretsmanager", region_name=region)
    secret = json.loads(sm.get_secret_value(SecretId=secret_name)["SecretString"])
    return secret.get("oracle", secret)  # support {"oracle": {...}} or a flat secret


def main() -> None:
    args = parse_args()

    # 1. wait for the VPN (unless explicitly skipped for local/mock testing)
    ready_file = os.environ.get("READY_FILE", "/shared/vpn-ready")
    if os.environ.get("WAIT_FOR_VPN", "true").lower() != "false":
        wait_for_vpn(ready_file, int(os.environ.get("VPN_WAIT_TIMEOUT", "120")))

    # 2. resolve script + Oracle secret (production via --tenant, else env)
    script_path = os.environ.get("SCRIPT_PATH", "/scripts/run.py")
    oracle_secret = os.environ.get("ORACLE_SECRET")

    if args.tenant:
        entry = load_tenant_entry(args.tenant)
        oracle_secret = entry.get("secret") or f"presa/etl/{args.tenant}"
        prefix = os.environ.get("SCRIPTS_S3_PREFIX", "").rstrip("/")
        fetch_script_from_s3(f"{prefix}/{entry['script']}", script_path)
        log(f"tenant={args.tenant} script={entry['script']} secret={oracle_secret}")
    elif os.environ.get("SCRIPT_S3"):
        fetch_script_from_s3(os.environ["SCRIPT_S3"], script_path)

    if not pathlib.Path(script_path).exists():
        log(f"✗ script not found: {script_path}")
        sys.exit(1)

    # 3. resolve Oracle creds → env for the script
    env = os.environ.copy()
    if args.tenant:
        env["TENANT_ID"] = args.tenant
    if oracle_secret:
        creds = fetch_oracle_creds(oracle_secret, os.environ.get("AWS_REGION", "us-east-2"))
        for env_key, secret_key in (
            ("ORACLE_HOST", "host"),
            ("ORACLE_PORT", "port"),
            ("ORACLE_SERVICE", "service"),
            ("ORACLE_SID", "sid"),
            ("ORACLE_USER", "user"),
            ("ORACLE_PASSWORD", "password"),
        ):
            if secret_key in creds:
                env[env_key] = str(creds[secret_key])

    # 4. run the script; its exit code becomes ours
    log(f"running {script_path}")
    result = subprocess.run([sys.executable, script_path], env=env)
    log(f"script exited with code {result.returncode}")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
