# -----------------------------------------------------------------------------
# Workload identity for the agent worker (EKS Pod Identity), same pattern as the
# PII gateway: pods using agent-worker/agent-worker get short-lived credentials
# for this role - no AWS keys anywhere.
#
# Only what a match job needs: the jobs queue, the synthetic datasets it reads,
# and the results prefix it writes. No Bedrock permission at all - the PII
# gateway is the only workload that can call a model.
# -----------------------------------------------------------------------------
locals {
  jobs_queue_arn          = data.terraform_remote_state.data.outputs.jobs_queue_arn
  raw_bucket_arn          = data.terraform_remote_state.data.outputs.raw_bucket_arn
  raw_kms_key_arn         = data.terraform_remote_state.data.outputs.raw_kms_key_arn
  deidentified_bucket_arn = data.terraform_remote_state.data.outputs.deidentified_bucket_arn
}

data "aws_iam_policy_document" "worker_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    # Only this cluster's agent-worker service account (Pod Identity session tags)
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/eks-cluster-arn"
      values   = [module.eks.cluster_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-namespace"
      values   = ["agent-worker"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-service-account"
      values   = ["agent-worker"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name                 = "${var.project_name}-agent-worker"
  description          = "Pod Identity role for the agent worker - jobs queue, synthetic data in, results out"
  assume_role_policy   = data.aws_iam_policy_document.worker_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid = "TakeAndFinishJobs"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    resources = [local.jobs_queue_arn]
  }

  statement {
    sid     = "ReadSyntheticPatientsAndNotes"
    actions = ["s3:GetObject"]
    resources = [
      "${local.raw_bucket_arn}/patients/v1/*",
      "${local.raw_bucket_arn}/notes/v1/*",
    ]
  }

  # Raw objects are encrypted with the raw key: Decrypt only when S3 asks on
  # the role's behalf, never a direct KMS call
  statement {
    sid       = "DecryptRawViaS3Only"
    actions   = ["kms:Decrypt"]
    resources = [local.raw_kms_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    sid       = "ReadTrials"
    actions   = ["s3:GetObject"]
    resources = ["${local.deidentified_bucket_arn}/trials/v1/*"]
  }

  statement {
    sid       = "WriteResults"
    actions   = ["s3:PutObject"]
    resources = ["${local.deidentified_bucket_arn}/results/v1/*"]
  }
}

resource "aws_iam_role_policy" "worker" {
  name   = "match-jobs"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_eks_pod_identity_association" "worker" {
  cluster_name    = module.eks.cluster_name
  namespace       = "agent-worker"
  service_account = "agent-worker"
  role_arn        = aws_iam_role.worker.arn
}

output "worker_role_arn" {
  description = "Pod Identity role used by the agent worker."
  value       = aws_iam_role.worker.arn
}
