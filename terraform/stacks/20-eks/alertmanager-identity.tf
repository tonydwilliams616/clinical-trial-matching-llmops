# -----------------------------------------------------------------------------
# Workload identity for Alertmanager (EKS Pod Identity), so it can email the
# project's Ctm* alerts through the ops-alerts SNS topic (00-account).
#
# One right: sns:Publish on that one topic. No keys anywhere - the same
# keyless pattern as the gateway and workers. The topic uses the AWS-managed
# SNS key, whose key policy already allows use through SNS within the account,
# so no KMS permission is needed here.
# -----------------------------------------------------------------------------
data "terraform_remote_state" "account" {
  backend = "s3"

  config = {
    bucket = "ctm-tfstate-${var.aws_account_id}"
    key    = "00-account/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  ops_alerts_topic_arn = data.terraform_remote_state.account.outputs.ops_alerts_topic_arn
  # kube-prometheus-stack's Alertmanager service account (release "monitoring"),
  # also set explicitly in gitops/bootstrap/monitoring.yaml so the two can't drift
  alertmanager_service_account = "monitoring-kube-prometheus-alertmanager"
}

data "aws_iam_policy_document" "alertmanager_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    # Only this cluster's monitoring/<alertmanager> service account
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/eks-cluster-arn"
      values   = [module.eks.cluster_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-namespace"
      values   = ["monitoring"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-service-account"
      values   = [local.alertmanager_service_account]
    }
  }
}

resource "aws_iam_role" "alertmanager" {
  name                 = "${var.project_name}-alertmanager"
  description          = "Pod Identity role for Alertmanager: publish Ctm* alerts to the ops-alerts SNS topic"
  assume_role_policy   = data.aws_iam_policy_document.alertmanager_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "alertmanager_sns" {
  statement {
    sid       = "PublishOpsAlerts"
    actions   = ["sns:Publish"]
    resources = [local.ops_alerts_topic_arn]
  }
}

resource "aws_iam_role_policy" "alertmanager_sns" {
  name   = "publish-ops-alerts"
  role   = aws_iam_role.alertmanager.id
  policy = data.aws_iam_policy_document.alertmanager_sns.json
}

resource "aws_eks_pod_identity_association" "alertmanager" {
  cluster_name    = module.eks.cluster_name
  namespace       = "monitoring"
  service_account = local.alertmanager_service_account
  role_arn        = aws_iam_role.alertmanager.arn
}
