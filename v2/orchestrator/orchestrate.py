#!/usr/bin/env python3
"""PRESA ETL orchestrator — fan out one worker Job per enabled tenant.

Reads tenants.json from S3, then for each ENABLED tenant stamps the worker Job
template (unique name + `--tenant <id>` + the tenant's VPN secret) and creates it
via the Kubernetes API. Runs as a Job (triggered by a CronJob), under an
`orchestrator` ServiceAccount whose RBAC allows creating Jobs in the `etl` namespace.

The worker is generic; identity-per-tenant is just the `--tenant` arg stamped here.
"""

import copy
import datetime
import json
import os
import re
import sys

import boto3
import yaml
from kubernetes import client, config


def log(msg: str) -> None:
    print(f"[orchestrator] {msg}", flush=True)


def k8s_name(tenant_id: str) -> str:
    """Tenant id → DNS-1123 fragment (e.g. P_COMON_MG_MG → p-comon-mg-mg)."""
    return re.sub(r"[^a-z0-9-]", "-", tenant_id.lower()).strip("-")


def load_tenants(uri: str) -> list:
    bucket, key = uri.removeprefix("s3://").split("/", 1)
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    return json.loads(body).get("tenants", [])


def render_job(base: dict, tenant_id: str, namespace: str, vpn_enabled: bool = True) -> tuple[str, dict]:
    job = copy.deepcopy(base)
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
    name = f"etl-{k8s_name(tenant_id)}-{stamp}"[:63]

    job["metadata"]["name"] = name
    job["metadata"]["namespace"] = namespace
    job["metadata"].setdefault("labels", {})["tenant"] = tenant_id
    # label the POD too, so `kubectl logs -l tenant=<id>` works (logs select pods)
    job["spec"]["template"].setdefault("metadata", {}).setdefault("labels", {})["tenant"] = tenant_id

    spec = job["spec"]["template"]["spec"]
    for c in spec.get("containers", []):
        if c["name"] == "worker":
            c["args"] = ["--tenant", tenant_id]

    if vpn_enabled:
        # the sidecar self-fetches its VPN secret; just tell it which tenant it is
        for c in spec.get("initContainers", []):
            if c["name"] == "vpn-sidecar":
                for e in c.get("env", []):
                    if e["name"] == "TENANT_ID":
                        e["value"] = tenant_id
    else:
        # testing without client creds: drop the sidecar and don't wait for a VPN
        spec.pop("initContainers", None)
        for c in spec.get("containers", []):
            if c["name"] == "worker":
                c.setdefault("env", []).append({"name": "WAIT_FOR_VPN", "value": "false"})

    return name, job


def main() -> None:
    namespace = os.environ.get("NAMESPACE", "etl")
    tenants_s3 = os.environ.get("TENANTS_S3")
    if not tenants_s3:
        log("✗ TENANTS_S3 is required (s3://bucket/tenants.json)")
        sys.exit(2)
    template_path = os.environ.get("WORKER_JOB_TEMPLATE", "/app/worker-job.template.yaml")
    vpn_enabled = os.environ.get("VPN_ENABLED", "true").lower() != "false"

    # ${VAR} substitution for the global values (image tags, S3 locations, region)
    with open(template_path) as f:
        base = yaml.safe_load(os.path.expandvars(f.read()))

    config.load_incluster_config()
    batch = client.BatchV1Api()

    tenants = load_tenants(tenants_s3)
    enabled = [t for t in tenants if t.get("enabled")]
    log(f"{len(enabled)} enabled tenant(s) of {len(tenants)} total")

    log(f"VPN sidecar: {'enabled' if vpn_enabled else 'DISABLED (test mode)'}")
    created = failed = 0
    for t in enabled:
        tid = t["id"]
        name, job = render_job(base, tid, namespace, vpn_enabled)
        try:
            batch.create_namespaced_job(namespace=namespace, body=job)
            log(f"✓ created Job {name} (tenant {tid})")
            created += 1
        except Exception as exc:  # noqa: BLE001 — report and continue with other tenants
            log(f"✗ failed to create Job for {tid}: {exc}")
            failed += 1

    log(f"done — {created} created, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
