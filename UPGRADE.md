# EKS upgrade runbook: 1.36 → 1.37

How the cluster is upgraded in place, how "no downtime" is measured, and what
happens if it goes wrong. Written before the upgrade; the results are recorded
in the README.

## Readiness (checked 27 Oct 2026)

| Component | Version | Tested up to | Action |
| --- | --- | --- | --- |
| EKS 1.37 | – | – | Standard support in us-east-1 since 2 Oct 2026 |
| Karpenter | 1.15.1 | 1.37 (`MaxK8sVersion` in `pkg/providers/version`) | Upgraded from 1.14.1, which stops at 1.36 (#85) |
| KEDA | 2.21.0 | 1.36 | Upgraded from 2.20.2, which stopped at 1.35 (#86) |
| Argo CD | 3.5 | 1.36 | 3.6 is still a release candidate |
| EKS add-ons (VPC CNI, CoreDNS, kube-proxy, Pod Identity agent, metrics-server) | `most_recent` | managed by AWS | Move to their 1.37 builds in the same apply |
| Nodes | AL2023 | – | Already cgroup v2; the 1.37 cgroup v1 change does not apply |
| Our manifests | – | – | pluto 5.24.4 against `gitops/`, target v1.37.0: no deprecated APIs |

**Accepted risk:** KEDA and Argo CD do not list 1.37 yet. Both use only stable
Kubernetes APIs, so they are verified live instead (KEDA scales the workers
from zero after the upgrade; Argo CD keeps every app Synced and Healthy and
completes a fresh sync). If either fails, see Rollback.

## Order

Each step finishes before the next starts. Kubernetes allows nodes to run one
minor version behind the control plane, so 1.36 nodes keep working under a
1.37 control plane while they are replaced.

| # | Step | How | About |
| --- | --- | --- | --- |
| 0 | Cluster up at 1.36 with Karpenter 1.15.1 and KEDA 2.21.0 | Terraform Deploy → `all` | 25 min |
| 1 | Upgrade insights | `aws eks list-insights` (below): any ERROR stops the upgrade | 2 min |
| 2 | Start the evidence | k6 soak, queue jobs every 10 minutes, Grafana open | 5 min |
| 3 | Control plane, managed add-ons, system node group | Merge the PR setting `kubernetes_version = "1.37"`; approve its deploy run. One apply updates the cluster, then the add-ons and the system node group (a managed rolling update that respects PDBs) | 30–40 min |
| 4 | Workload nodes | Automatic: the EC2NodeClass uses `al2023@latest`, which now resolves to the 1.37 AMI, so Karpenter marks the nodes as drifted and replaces them one at a time | 10–15 min |
| 5 | Nodes held by monitoring pods | After the k6 summary and screenshots (below) | 10 min |
| 6 | Verify, then tear down | Checks below | 15 min |

### Step 5: the do-not-disrupt pods

Prometheus, Grafana, Alertmanager, Tempo and the k6 Job carry
`karpenter.sh/do-not-disrupt: "true"`, so Karpenter never moves them during a
test session. The same annotation stops drift from replacing their nodes (the
Karpenter docs: such nodes are excluded from drift unless the NodeClaim has a
`terminationGracePeriod`).

Decision for this upgrade: keep the annotation and release those nodes by hand
once the evidence is captured. The monitoring stack has no persistent volumes
(by design for a cluster rebuilt every session), so moving its pods loses the
metrics and traces collected so far. Capture first, then move:

1. k6 has finished and its summary is saved; Grafana screenshots are taken.
2. Cordon the remaining 1.36 Karpenter nodes, so the pods don't land back on them:
   ```
   kubectl get nodes -l karpenter.sh/nodepool -o jsonpath='{range .items[*]}{.metadata.name} {.status.nodeInfo.kubeletVersion}{"\n"}{end}' | awk '$2 ~ /^v1\.36/ {print $1}' | xargs kubectl cordon
   ```
3. Delete the pinned pods; their controllers recreate them on 1.37 nodes:
   ```
   kubectl -n monitoring delete pod -l 'app.kubernetes.io/name in (prometheus,alertmanager,grafana,tempo)'
   ```
4. Karpenter then finds the cordoned nodes free of blocking pods and replaces them.

For a long-lived cluster, the better answer is a `terminationGracePeriod` on
the NodePool, so drift can always proceed (backlog).

## Evidence of no downtime

"No downtime" means the application kept answering, not that kubectl never
blinked: the EKS API endpoint can be briefly unavailable while the control
plane is replaced, and that doesn't affect traffic between pods.

| Signal | How | Pass |
| --- | --- | --- |
| Gateway requests | `kubectl apply -k loadtest/gateway-soak` (12 a minute for 90 minutes) | k6 thresholds pass; `server_errors` 0 |
| Match jobs | `loadtest/queue-burst.sh 2` every 10 minutes (worker pods drained during node replacement) | Every job has a result file in S3; `ctm-match-jobs-dlq` stays empty |
| Gateway pods | PDB (`maxUnavailable: 1`), at least two replicas (HPA) spread across zones | Never fewer than 1 Ready pod |
| Alerts | Prometheus alerts page | No `CtmGatewayDown`, `CtmJobsFailing` or burn-rate alert fires |
| Versions | `kubectl get nodes`; `aws eks describe-cluster` | Control plane and every node on v1.37 |

Commands for the session:

```
aws eks list-insights --region us-east-1 --cluster-name ctm-eks --filter categories=UPGRADE_READINESS --query 'insights[].[name,insightStatus.status]' --output table
```

```
for i in 1 2 3 4 5 6; do loadtest/queue-burst.sh 2; sleep 600; done
```

```
kubectl get nodes -L karpenter.sh/nodepool -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,POOL:.metadata.labels.karpenter\.sh/nodepool -w
```

## Rollback

The EKS control plane cannot be downgraded. What happens depends on where it fails:

| Fails at | Response |
| --- | --- |
| Step 1 (insights ERROR) or before step 3 | Stop. Nothing has changed |
| Step 3, control plane or add-ons | Fix forward: pin the failing add-on to its last good version in `20-eks`, or revert the Karpenter/KEDA PR, then re-apply |
| A workload on 1.37 | Same: fix forward, or revert that component's version |
| Unrecoverable | Rebuild: destroy the ephemeral stacks, revert the version PR (back to 1.36), Deploy → `all`. About 25 minutes |

A rebuild loses nothing that matters: the cluster is rebuilt from Terraform
and Git every session, and the data lives outside it (S3 buckets, the SQS
queue, ECR images, Secrets Manager), in permanent stacks the upgrade doesn't
touch.

## As run (28 Oct 2026)

The upgrade worked as planned; results are in the README. Two things went differently, and the next upgrade should do them this way:

1. **Release the pinned nodes during the soak, not after it.** The two drifted workload nodes held both gateway pods as well as the pinned pods. Waiting for k6 to finish would have moved the gateway with no traffic running, proving nothing. Instead: screenshot Grafana, cordon both old nodes, delete the monitoring pods (Karpenter then replaced that node and moved one gateway pod), and delete the gateway pod left on the k6 node once its replacement was Ready. The k6 node went last, after the soak.
2. **Save the k6 summary before the pod's node can go.** When the k6 pod finished, its node stopped being pinned and Karpenter removed it at once, with the pod's logs. Keep a `kubectl logs -f` stream attached to the end, or have k6 write its summary somewhere that outlives the node.

Timings: control plane, add-ons and system nodes about 20 minutes (15:46–16:05); each workload node about 3 minutes once released.
