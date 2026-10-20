# -----------------------------------------------------------------------------
# KEDA - AWS side only. Argo CD installs KEDA (gitops/bootstrap/keda.yaml); this
# gives its operator a Pod Identity role that can read the match job queue's
# depth, and nothing else. KEDA scales the agent workers on that number - down
# to zero when the queue is empty.
# -----------------------------------------------------------------------------
data "terraform_remote_state" "data" {
  backend = "s3"

  config = {
    bucket = "ctm-tfstate-${var.aws_account_id}"
    key    = "18-data/terraform.tfstate"
    region = var.aws_region
  }
}

data "aws_iam_policy_document" "keda_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    # Only this cluster's KEDA operator service account (Pod Identity session tags)
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/eks-cluster-arn"
      values   = ["arn:aws:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/${local.cluster_name}"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-namespace"
      values   = ["keda"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-service-account"
      values   = ["keda-operator"]
    }
  }
}

resource "aws_iam_role" "keda" {
  name                 = "${var.project_name}-keda-operator"
  description          = "Pod Identity role for the KEDA operator - read the match job queue depth only"
  assume_role_policy   = data.aws_iam_policy_document.keda_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "keda" {
  statement {
    sid       = "ReadJobQueueDepth"
    actions   = ["sqs:GetQueueAttributes"]
    resources = [data.terraform_remote_state.data.outputs.jobs_queue_arn]
  }
}

resource "aws_iam_role_policy" "keda" {
  name   = "read-job-queue-depth"
  role   = aws_iam_role.keda.id
  policy = data.aws_iam_policy_document.keda.json
}

# Exists before KEDA is installed, so its pods get credentials from their first start
resource "aws_eks_pod_identity_association" "keda" {
  cluster_name    = local.cluster_name
  namespace       = "keda"
  service_account = "keda-operator"
  role_arn        = aws_iam_role.keda.arn
}
