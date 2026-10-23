# Chaos experiments

Each experiment breaks one thing on purpose and states what should happen.
The point is to test the claims the design makes: SQS retries instead of
losing work, workers stop politely, the gateway survives losing a pod,
alerts fire for real problems (and stay quiet for blips), and observability
failures never affect matching.

Run during an EKS session, with the dashboard and the Prometheus alerts page
open (port-forwards in `loadtest/README.md`). The script refuses to run unless
kubectl points at this project's cluster. Each experiment is undone by
Kubernetes itself (Deployments replace deleted pods), except `keda-pause`,
which has a matching `keda-resume`.

| Experiment | What breaks | Expected behaviour | Expected alert |
| --- | --- | --- | --- |
| `gateway-pod` | One of the 2+ gateway pods | Service routes around it; replacement Ready after the model loads | None |
| `gateway-all` | Every gateway pod at once | In-flight jobs fail and stay on the queue; retried after 5 min; complete | `CtmJobsFailing`. Not `CtmGatewayDown` (needs 5 min down) |
| `worker-graceful` | A busy worker, SIGTERM | Finishes its job (330 s grace), deletes the message, exits | None |
| `worker-abrupt` | A busy worker, killed in 1 s | Job reappears after the 5 min visibility timeout; completes once | None until the retry; then clean |
| `keda-pause` / `keda-resume` | Scaling held at zero | Jobs pile up; drain once resumed | `CtmQueueNotDraining` (critical) |
| `tempo-pod` | The trace store | Matching, latency and results unchanged; gap in traces | None |

Suggested order, with jobs flowing (`loadtest/queue-burst.sh 2` before each
worker or gateway experiment): `tempo-pod`, `gateway-pod`, `worker-graceful`,
`worker-abrupt`, `gateway-all`, `keda-pause` then `keda-resume`.

## Recording results

For each experiment, note what happened against the expectation, with a
screenshot where it shows something (alerts firing and resolving, the queue
panel, a retried job's traces). An expectation that doesn't hold is a result
too: write it down as a finding and a backlog item.

## Not covered yet

- Node loss (a Karpenter node deleted under the gateway).
- Bedrock throttling or an expired model profile.
- Availability-zone failure.
A tool such as Chaos Mesh could schedule these repeatably; for one proof
session, plain kubectl keeps every step visible.
