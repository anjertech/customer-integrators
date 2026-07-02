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

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time
from string import Template


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

    bucket, key = _s3_split(uri)
    return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()


def _s3_split(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        log(f"✗ expected s3:// URI, got {uri}")
        sys.exit(2)
    bucket, key = uri.removeprefix("s3://").split("/", 1)
    return bucket, key


def _s3_join(prefix: str, key: str) -> str:
    if key.startswith("s3://"):
        return key
    if not prefix:
        log("✗ tenant script entries require SCRIPTS_S3_PREFIX unless they are full s3:// URIs")
        sys.exit(2)
    return f"{prefix.rstrip('/')}/{key.lstrip('/')}"


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


def progress_prefix(entry: dict, tenant_id: str | None) -> str:
    explicit = entry.get("progress_s3_prefix") or entry.get("progressPrefix")
    if explicit:
        return str(explicit).rstrip("/")
    base = os.environ.get("PROGRESS_S3_PREFIX", "").rstrip("/")
    if base and tenant_id:
        return f"{base}/{tenant_id}"
    return base


def sync_progress_from_s3(prefix: str, dest_dir: str) -> None:
    if not prefix:
        return
    import boto3

    bucket, key_prefix = _s3_split(prefix.rstrip("/") + "/")
    client = boto3.client("s3")
    paginator = client.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            name = pathlib.PurePosixPath(key).name
            if not name.startswith("progress") or not name.endswith(".json"):
                continue
            pathlib.Path(dest_dir, name).write_bytes(
                client.get_object(Bucket=bucket, Key=key)["Body"].read()
            )
            count += 1
    log(f"restored {count} progress file(s) from {prefix}")


def upload_progress_to_s3(prefix: str, source_dir: str) -> None:
    if not prefix:
        return
    import boto3

    bucket, key_prefix = _s3_split(prefix.rstrip("/") + "/")
    client = boto3.client("s3")
    count = 0
    for path in pathlib.Path(source_dir).glob("progress*.json"):
        client.upload_file(str(path), bucket, f"{key_prefix}{path.name}")
        count += 1
    log(f"uploaded {count} progress file(s) to {prefix}")


def fetch_tenant_bundle(entry: dict, default_script_path: str) -> str:
    script = entry.get("script")
    if not script:
        log("✗ tenant entry requires a script field")
        sys.exit(2)

    prefix = os.environ.get("SCRIPTS_S3_PREFIX", "").rstrip("/")
    files = list(entry.get("files") or [])
    if script not in files:
        files.insert(0, script)

    script_dest = default_script_path
    if default_script_path == "/scripts/run.py":
        script_dest = str(pathlib.Path("/scripts") / script)

    for file_key in files:
        dest = pathlib.Path("/scripts") / file_key
        fetch_script_from_s3(_s3_join(prefix, file_key), str(dest))

    return script_dest


def fetch_secret(secret_name: str, region: str) -> dict:
    import boto3

    log(f"fetching worker secret from Secrets Manager: {secret_name}")
    sm = boto3.client("secretsmanager", region_name=region)
    return json.loads(sm.get_secret_value(SecretId=secret_name)["SecretString"])


def _expand(value: str, env: dict[str, str]) -> str:
    return Template(value).safe_substitute(env)


def tenant_env(entry: dict, env: dict[str, str]) -> dict[str, str]:
    extra = entry.get("env") or {}
    if not isinstance(extra, dict):
        log("✗ tenant env must be an object")
        sys.exit(2)
    return {str(k): _expand(str(v), env) for k, v in extra.items()}


def tenant_args(entry: dict, env: dict[str, str]) -> list[str]:
    raw = entry.get("args", entry.get("script_args", []))
    if isinstance(raw, str):
        raw = shlex.split(raw)
    if not isinstance(raw, list):
        log("✗ tenant args/script_args must be a list or shell-style string")
        sys.exit(2)
    return [_expand(str(value), env) for value in raw]


def redact_args(args: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for value in args:
        lowered = value.lower()
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        if lowered in {"--password", "--client-secret", "--connection-string"}:
            redacted.append(value)
            redact_next = True
            continue
        if any(marker in lowered for marker in ("password=", "pwd=", "secret=")):
            redacted.append("[REDACTED]")
            continue
        redacted.append(value)
    return redacted


def main() -> None:
    args = parse_args()

    # 1. wait for the VPN (unless explicitly skipped for local/mock testing)
    ready_file = os.environ.get("READY_FILE", "/shared/vpn-ready")
    if os.environ.get("WAIT_FOR_VPN", "true").lower() != "false":
        wait_for_vpn(ready_file, int(os.environ.get("VPN_WAIT_TIMEOUT", "120")))

    # 2. resolve script + Oracle secret (production via --tenant, else env)
    script_path = os.environ.get("SCRIPT_PATH", "/scripts/run.py")
    oracle_secret = os.environ.get("ORACLE_SECRET")
    entry: dict = {}

    if args.tenant:
        entry = load_tenant_entry(args.tenant)
        oracle_secret = entry.get("secret") or f"presa/etl/{args.tenant}"
        script_path = fetch_tenant_bundle(entry, script_path)
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
        secret = fetch_secret(oracle_secret, os.environ.get("AWS_REGION", "us-east-2"))
        for key, value in (secret.get("env") or {}).items():
            env[str(key)] = str(value)

        # Support {"oracle": {...}} for combined VPN/worker secrets and flat
        # Oracle-only secrets for local or early tenant configs.
        creds = secret.get("oracle", secret)
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

    if entry:
        env.update(tenant_env(entry, env))
    script_args = tenant_args(entry, env) if entry else []

    script_dir = str(pathlib.Path(script_path).parent)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (script_dir, env.get("PYTHONPATH"), "/app") if part
    )
    progress_s3 = progress_prefix(entry, args.tenant)
    if args.tenant and not progress_s3:
        log("WARNING: PROGRESS_S3_PREFIX is not set; progress*.json will be pod-local and ephemeral")
    sync_progress_from_s3(progress_s3, script_dir)

    # 4. run the script; its exit code becomes ours
    if script_args:
        log(f"running {script_path} args={redact_args(script_args)}")
    else:
        log(f"running {script_path}")
    result = subprocess.run([sys.executable, script_path, *script_args], env=env, cwd=script_dir)
    upload_progress_to_s3(progress_s3, script_dir)
    log(f"script exited with code {result.returncode}")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
