# -----------------------------------------------------------------------------
# Match job queue. A job asks "shortlist patients for trial X"; agent workers on
# EKS take jobs from here, and KEDA scales the workers on the queue's depth.
#
# Permanent and effectively free: SQS bills per request, not per hour, so jobs
# can wait here while the cluster is torn down.
#
# Messages carry identifiers only (job ID, trial ID, cohort reference) - never
# patient text. Notes stay in S3 and are masked by the PII gateway before any
# model sees them.
# -----------------------------------------------------------------------------
resource "aws_sqs_queue" "jobs_dlq" {
  name = "${var.project_name}-match-jobs-dlq"

  # Failed jobs are kept for the maximum 14 days, for inspection and redrive
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "jobs" {
  name = "${var.project_name}-match-jobs"

  # How long a job stays hidden after a worker takes it. Longer than a job's
  # worst-case run time (several model calls), so two workers never process
  # the same job at once.
  visibility_timeout_seconds = 300

  message_retention_seconds = 345600 # 4 days
  receive_wait_time_seconds = 20     # long polling: fewer empty, billable receives
  sqs_managed_sse_enabled   = true

  # A job that fails 3 times moves to the dead-letter queue instead of
  # retrying forever
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = 3
  })
}

# Only the jobs queue may send messages to the dead-letter queue
resource "aws_sqs_queue_redrive_allow_policy" "jobs_dlq" {
  queue_url = aws_sqs_queue.jobs_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.jobs.arn]
  })
}

# Refuse any request that isn't over TLS, on both queues
data "aws_iam_policy_document" "queue_tls_only" {
  for_each = {
    jobs = aws_sqs_queue.jobs.arn
    dlq  = aws_sqs_queue.jobs_dlq.arn
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["sqs:*"]
    resources = [each.value]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sqs_queue_policy" "jobs" {
  queue_url = aws_sqs_queue.jobs.id
  policy    = data.aws_iam_policy_document.queue_tls_only["jobs"].json
}

resource "aws_sqs_queue_policy" "jobs_dlq" {
  queue_url = aws_sqs_queue.jobs_dlq.id
  policy    = data.aws_iam_policy_document.queue_tls_only["dlq"].json
}

output "jobs_queue_url" {
  description = "URL of the match job queue - used by the agent worker and KEDA."
  value       = aws_sqs_queue.jobs.id
}

output "jobs_queue_arn" {
  description = "ARN of the match job queue - for IAM policies in 20-eks."
  value       = aws_sqs_queue.jobs.arn
}

output "jobs_queue_name" {
  description = "Name of the match job queue - KEDA's SQS scaler uses it."
  value       = aws_sqs_queue.jobs.name
}

output "jobs_dlq_arn" {
  description = "ARN of the dead-letter queue for failed match jobs."
  value       = aws_sqs_queue.jobs_dlq.arn
}
