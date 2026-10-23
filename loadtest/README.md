# Load tests

Two tests, run by hand during an EKS session with the monitoring stack up.
Neither is synced by Argo CD: they exist in the cluster only while they run.

| Test | What it drives | What it proves |
| --- | --- | --- |
| `gateway/` (k6 Job) | `/v1/assess` directly, ramping 0 → 1 → 3 requests/s over 9 minutes | Latency and error rate against the SLOs (p95 under 5 s, under 1% 5xx); where Bedrock starts throttling; the gateway's CPU autoscaling |
| `queue-burst.sh` | A burst of match jobs on SQS | KEDA scales workers 0 → 3 and back to 0; every job finishes; traces show one job end to end |

Synthetic data only: the k6 notes are generated with planted fake identifiers
(555-01xx phones, example.com emails), and the queue jobs use the synthetic
patient set.

## Cost

Bedrock (Claude Haiku 4.5) is the only usage-billed part:

- Gateway test: about 1,000 requests of roughly 700 input and 50 output tokens - around $1.
- Queue burst: up to 100 questions per job; the default 6 jobs is at most 600 questions - under $1.

Both run on the cluster's existing nodes. The cluster itself is the main cost
of the session, so tear it down afterwards as usual.

## Before you start

1. Cluster up, all Argo CD apps Synced and Healthy (including `monitoring`, `tempo`, `keda`).
2. Grafana: `kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80`, then open the
   "Clinical trial matching - flow" dashboard, time range "Last 30 minutes".
3. Prometheus alerts: `kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090`,
   then open http://localhost:9090/alerts.

## Test 1: gateway ramp (k6)

```
kubectl apply -k loadtest/gateway && kubectl -n loadtest logs -f job/k6-gateway
```

k6 prints a summary at the end. The Job **fails** if a threshold is crossed:
p95 over 5 s for answered requests, 1% or more server errors, or under 99% of
checks passing. `model_unavailable_502` counts Bedrock failures (usually
throttling); `refusals` counts safety-check 422s, which should be zero.

Watch the gateway scale on CPU while it runs:

```
kubectl -n pii-gateway get hpa,pods -w
```

Clean up (also removes the temporary firewall opening into the gateway):

```
kubectl delete -k loadtest/gateway
```

## Test 2: queue burst (KEDA)

```
loadtest/queue-burst.sh
```

Then `kubectl get scaledobject,deploy,pods -n agent-worker -w`: workers go
0 → 3 within a minute (queueLength 2, so 6 jobs = 3 workers), the queue
drains, and after the 300 s cooldown they return to 0. The script prints the
command to list the results in S3.

## What to capture for the README

- Dashboard during test 1: requests by status, latency p50/p95/p99, Bedrock tokens.
- Dashboard during test 2: "Queue depth and workers" showing 0 → 3 → 0.
- The k6 summary (thresholds passed or not).
- Grafana Explore → Tempo: one `match_job` trace with `gateway.assess` spans
  and the gateway's `mask`, `leftover_check` and `bedrock.converse` inside.
- Prometheus alerts page: the rules listed, and which fired (if any).
