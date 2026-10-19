# pii-gateway on Kubernetes

Kustomize manifests for the PII gateway. One base, two overlays:

| Overlay | Image | Placement |
| --- | --- | --- |
| `overlays/eks` | ECR `ctm/pii-gateway:<commit SHA>` (benchmark-gated, immutable) | Karpenter workload nodes |
| `overlays/kind` | `pii-gateway:local`, built on your machine | any kind worker; HPA capped at 4 |

What the base provides:

- **Deployment** - non-root, read-only root filesystem, all Linux capabilities dropped, startup/readiness/liveness probes, no Kubernetes API token
- **HPA** - 2 to 6 copies, scaling on CPU at 70% of the request
- **PodDisruptionBudget** - drains and consolidation remove at most one copy at a time
- **Topology spread** - copies spread across zones (hard rule) and nodes (best effort)
- **NetworkPolicies** - default deny; only the `agent-worker` namespace may call the gateway; outbound only DNS and HTTPS inside the VPC (the Bedrock endpoint), no internet
- **Namespace** with Pod Security Admission `restricted`

## Local test on kind (free)

Needs Docker Desktop and `kind`. Run from the repo root.

1. Create a 3-worker cluster with fake zones, and install metrics-server (the HPA reads CPU from it):

   ```
   kind create cluster --name ctm --config kind/cluster.yaml && kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml && kubectl -n kube-system patch deployment metrics-server --type=json -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
   ```

2. Build the image locally, load it into kind, deploy and wait:

   ```
   docker build -t pii-gateway:local services/pii-gateway && kind load docker-image pii-gateway:local --name ctm && kubectl apply -k gitops/apps/pii-gateway/overlays/kind && kubectl -n pii-gateway rollout status deployment/pii-gateway --timeout=180s
   ```

3. Spread - two copies on different zones:

   ```
   kubectl -n pii-gateway get pods -o wide && kubectl get nodes -L topology.kubernetes.io/zone
   ```

4. NetworkPolicy - a caller outside `agent-worker` is blocked (times out), a caller inside it is allowed:

   ```
   kubectl run blocked --rm -i --restart=Never --image=busybox:1.36 -- wget -q -T 5 -O- http://pii-gateway.pii-gateway/healthz ; kubectl create namespace agent-worker && kubectl -n agent-worker run allowed --rm -i --restart=Never --image=busybox:1.36 -- wget -q -T 5 -O- http://pii-gateway.pii-gateway/healthz
   ```

5. HPA - generate load from `agent-worker` and watch copies being added (Ctrl+C to stop watching):

   ```
   kubectl -n agent-worker create deployment load --image=busybox:1.36 --replicas=3 -- sh -c 'while true; do wget -q -O- --header "content-type: application/json" --post-data "{\"text\":\"Seen John Smith, MRN 4821937, phone (617) 555-0147.\"}" http://pii-gateway.pii-gateway/v1/mask >/dev/null; done' && kubectl -n pii-gateway get hpa -w
   ```

   Then stop the load: `kubectl -n agent-worker delete deployment load` (copies scale back down after the 2-minute stabilisation window).

6. PodDisruptionBudget - `ALLOWED DISRUPTIONS` is 1, and draining two gateway nodes at once is refused for the second pod until the first is replaced:

   ```
   kubectl -n pii-gateway get pdb
   ```

7. Clean up: `kind delete cluster --name ctm`
