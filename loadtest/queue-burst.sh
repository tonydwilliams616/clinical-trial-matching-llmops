#!/usr/bin/env bash
# Puts a burst of match jobs on the queue to watch KEDA scale the workers
# from zero to three and back. Run from your machine with AWS credentials for
# the project account; nothing needs to be installed in the cluster.
#
#   loadtest/queue-burst.sh            6 jobs for NCT06836479 (NOURISH)
#   loadtest/queue-burst.sh 10 NCT05580536
#
# Each job asks the model up to 100 questions (20 candidates x 5 criteria),
# so jobs are capped at 20 per burst to keep Bedrock spend small.
set -euo pipefail

JOBS="${1:-6}"
TRIAL="${2:-NCT06836479}"

if ! [[ "$JOBS" =~ ^[0-9]+$ ]] || (( JOBS < 1 || JOBS > 20 )); then
  echo "jobs must be between 1 and 20" >&2
  exit 1
fi
if ! [[ "$TRIAL" =~ ^NCT[0-9]{8}$ ]]; then
  echo "trial must look like NCT01234567" >&2
  exit 1
fi

QUEUE_URL="$(aws sqs get-queue-url --queue-name ctm-match-jobs --query QueueUrl --output text)"
RUN="load-$(date -u +%Y%m%d-%H%M%S)"

for i in $(seq -w 1 "$JOBS"); do
  aws sqs send-message --queue-url "$QUEUE_URL" \
    --message-body "{\"job_id\": \"${RUN}-${i}\", \"nct_id\": \"${TRIAL}\"}" \
    --query MessageId --output text >/dev/null
done

echo "Queued ${JOBS} jobs for ${TRIAL} as ${RUN}-01..${JOBS}"
echo "Watch: kubectl get scaledobject,deploy,pods -n agent-worker -w"
echo "Results: aws s3 ls s3://ctm-deidentified-\$(aws sts get-caller-identity --query Account --output text)/results/v1/ | grep ${RUN}"
