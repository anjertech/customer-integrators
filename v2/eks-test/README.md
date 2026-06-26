# No-VPN EKS validation

Proves the **whole ETL pipeline on real EKS nodes, minus the VPN** — before you
have client credentials. Validates: ECR pulls, Pod Identity, the orchestrator
creating worker Jobs (RBAC), the worker's secret-fetch + thick-mode Oracle, and
`SELECT 1`. Only the `openfortivpn` dial is left unproven.

How it works: deploy the chart with `vpn.enabled=false` (orchestrator stamps
**sidecar-less** worker Jobs with `WAIT_FOR_VPN=false`), and point a test tenant at
an **in-cluster mock Oracle** instead of a client DB.

## Steps (cluster must be applied/running)
```bash
# 0. Create the namespace first (Helm stores its release in it)
kubectl create namespace etl
kubectl label namespace etl pod-security.kubernetes.io/enforce=privileged --overwrite

# 1. Deploy the mock Oracle into the etl namespace
kubectl apply -f eks-test/mock-oracle.yaml
kubectl rollout status deploy/oracle-mock -n etl   # ~1-2 min

# 2. A test secret pointing the worker at the mock (worker self-fetches it)
aws secretsmanager create-secret --region us-east-2 --name presa/etl/TEST \
  --secret-string '{"oracle":{"host":"oracle-mock.etl.svc.cluster.local","port":1521,"service":"FREEPDB1","user":"presa","password":"presa"}}'

# 3. Upload a test tenants.json + the test script to S3
echo '{"tenants":[{"id":"TEST","enabled":true,"script":"test_oracle_connection.py"}]}' > /tmp/tenants.json
aws s3 cp /tmp/tenants.json s3://presa-etl/tenants.json
aws s3 cp scripts/test_oracle_connection.py s3://presa-etl/scripts/test_oracle_connection.py

# 4. Install the chart with the VPN disabled
helm upgrade --install presa-etl ./chart -n etl --set vpn.enabled=false \
  --set image.orchestrator.tag=<sha> --set image.worker.tag=<sha>

# 5. Trigger the orchestrator now (don't wait for the schedule)
kubectl create job -n etl --from=cronjob/presa-etl-orchestrator manual-1

# 6. Watch it fan out + the worker pass
kubectl logs -n etl job/manual-1 -f                # orchestrator: "created Job etl-test-..."
kubectl get jobs -n etl
WJOB=$(kubectl get jobs -n etl -l tenant=TEST -o name | tail -1)
kubectl logs -n etl $WJOB -f                        # worker: "SELECT 1 FROM DUAL): 1"
```

✅ A worker logging `✓ Test query (SELECT 1 FROM DUAL): 1` means the entire pipeline
works on EKS. The remaining gap is only the real VPN dial (Stages 2–3 / with creds).

## Cleanup
```bash
kubectl delete job -n etl manual-1
kubectl delete -f eks-test/mock-oracle.yaml
aws secretsmanager delete-secret --region us-east-2 --name presa/etl/TEST --force-delete-without-recovery
# helm uninstall presa-etl -n etl   # if tearing the whole thing down
```
