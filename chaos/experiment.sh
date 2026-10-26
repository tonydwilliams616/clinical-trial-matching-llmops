#!/usr/bin/env bash
# Chaos experiments: break one thing on purpose, then check the system
# recovers and the right alarm (and only the right alarm) rings.
# Run by hand during an EKS session; see chaos/README.md for what to watch.
#
#   chaos/experiment.sh gateway-pod      kill one gateway pod
#   chaos/experiment.sh gateway-all      kill every gateway pod at once
#   chaos/experiment.sh worker-graceful  stop a busy worker the polite way
#   chaos/experiment.sh worker-abrupt    kill a busy worker with no warning
#   chaos/experiment.sh keda-pause       hold the workers at zero
#   chaos/experiment.sh keda-resume      undo keda-pause
#   chaos/experiment.sh tempo-pod        kill the trace store
set -euo pipefail

ACCOUNT_ID="359013545044"

# Guard: only ever run against this project's cluster
context="$(kubectl config current-context)"
if [[ "$context" != *"$ACCOUNT_ID"* ]]; then
  echo "Refusing to run: kubectl context '$context' is not the project cluster" >&2
  exit 1
fi

say() { printf '\n%s\n' "$*"; }

# Queues one job, waits for a worker that is running and not shutting down,
# then gives it a few seconds to be mid-job. A fixed sleep raced KEDA on EKS
# (25 Oct): from zero, KEDA can take ~30 s to start a worker, and a worker in
# its cool-down may already be terminating.
busy_worker() {
  local pod="" waited=0
  "$(dirname "$0")/../loadtest/queue-burst.sh" 1 >&2
  while [[ -z "$pod" ]]; do
    pod="$(kubectl -n agent-worker get pods -l app.kubernetes.io/name=agent-worker \
      --field-selector=status.phase=Running \
      -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.deletionTimestamp}{"\n"}{end}' 2>/dev/null \
      | awk 'NF == 1 { print $1; exit }' || true)"
    if [[ -z "$pod" ]]; then
      if (( waited >= 120 )); then
        echo "No worker started within 120 s - is KEDA paused? (chaos/experiment.sh keda-resume)" >&2
        exit 1
      fi
      sleep 2
      waited=$((waited + 2))
    fi
  done
  sleep "${BUSY_DELAY:-8}"  # a job takes ~28 s: 8 s in, it is mid-job
  echo "$pod"
}

case "${1:-}" in
  gateway-pod)
    say "Hypothesis: with 2+ replicas behind the Service, losing one gateway pod is barely visible."
    pod="$(kubectl -n pii-gateway get pods -l app.kubernetes.io/name=pii-gateway -o jsonpath='{.items[0].metadata.name}')"
    kubectl -n pii-gateway delete pod "$pod" --wait=false
    say "Watch: kubectl -n pii-gateway get pods -w   (replacement Ready after the model loads)"
    say "Expect: no alerts; at most an in-flight request fails and that job retries."
    ;;

  gateway-all)
    say "Hypothesis: a full gateway outage fails in-flight jobs, SQS retries them after the"
    say "5-minute visibility timeout, and they complete once the gateway is back."
    kubectl -n pii-gateway delete pod -l app.kubernetes.io/name=pii-gateway --wait=false
    say "Watch: kubectl -n pii-gateway get pods -w ; kubectl -n agent-worker logs -l app.kubernetes.io/name=agent-worker --tail=-1 -f"
    say "Expect: CtmJobsFailing fires (warning). CtmGatewayDown should NOT fire if pods are back within 5 minutes."
    say "Proof: the job's result file appears in S3 after the retry; Tempo shows a failed match_job then a successful one."
    ;;

  worker-graceful)
    pod="$(busy_worker)"
    say "Hypothesis: a polite stop (SIGTERM, 330 s grace) lets the worker finish its current job first."
    kubectl -n agent-worker delete pod "$pod" --wait=false
    say "Watch: kubectl -n agent-worker logs $pod -f   (expect job_done, then stopped)"
    say "Expect: no failed job, no alert. This is what a scale-down or node drain does."
    ;;

  worker-abrupt)
    pod="$(busy_worker)"
    say "Hypothesis: a hard kill (like a spot reclaim) loses the job in progress, but not the job itself:"
    say "the message was never deleted, so SQS hands it to a worker again after 5 minutes."
    kubectl -n agent-worker delete pod "$pod" --grace-period=1 --wait=false
    say "Watch: aws sqs get-queue-attributes --queue-url \$(aws sqs get-queue-url --queue-name ctm-match-jobs --query QueueUrl --output text) --attribute-names ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessages"
    say "Expect: the job completes on the retry; its result file is written once (same key, so a repeat is harmless)."
    ;;

  keda-pause)
    say "Hypothesis: if scaling stops while jobs wait, CtmQueueNotDraining fires within ~5 minutes."
    kubectl -n agent-worker annotate scaledobject agent-worker autoscaling.keda.sh/paused-replicas="0" --overwrite
    say "Now queue work: loadtest/queue-burst.sh 2"
    say "Watch: Prometheus alerts page; dashboard 'Queue depth and workers' (jobs waiting, workers 0)."
    say "If the alert does NOT fire, that is a finding: KEDA may stop reporting queue depth while paused."
    say "Undo with: chaos/experiment.sh keda-resume"
    ;;

  keda-resume)
    kubectl -n agent-worker annotate scaledobject agent-worker autoscaling.keda.sh/paused-replicas-
    say "Expect: workers scale up, the queue drains, CtmQueueNotDraining resolves."
    ;;

  tempo-pod)
    say "Hypothesis: losing the trace store never affects matching. Apps drop spans they can't send."
    pod="$(kubectl -n monitoring get pods -l app.kubernetes.io/name=tempo -o jsonpath='{.items[0].metadata.name}')"
    kubectl -n monitoring delete pod "$pod" --wait=false
    say "Run this during a load test or queue burst."
    say "Expect: gateway latency and job results unchanged; a gap in traces while Tempo restarts (its data is ephemeral)."
    ;;

  *)
    # Usage: the comment block at the top of this file, without the "# "
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
    exit 1
    ;;
esac
