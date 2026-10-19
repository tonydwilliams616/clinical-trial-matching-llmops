# -----------------------------------------------------------------------------
# Workload identity for the PII gateway (EKS Pod Identity). Pods using the
# pii-gateway/pii-gateway service account receive short-lived credentials for
# this role - no AWS keys in the cluster, in Git or in the image.
#
# No permissions yet: phase 3 adds bedrock:InvokeModel on the project's own
# inference profile only. The gateway is the only workload that will ever get
# Bedrock access.
# -----------------------------------------------------------------------------
data "aws_iam_policy_document" "gateway_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    # Pod Identity adds session tags naming the cluster, namespace and service
    # account of the pod asking. Only this cluster's pii-gateway/pii-gateway
    # service account can assume the role, even if another association points
    # at it by mistake.
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/eks-cluster-arn"
      values   = [module.eks.cluster_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-namespace"
      values   = ["pii-gateway"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-service-account"
      values   = ["pii-gateway"]
    }
  }
}

resource "aws_iam_role" "gateway" {
  name                 = "${var.project_name}-pii-gateway"
  description          = "Pod Identity role for the PII gateway (Bedrock access added in phase 3)"
  assume_role_policy   = data.aws_iam_policy_document.gateway_trust.json
  max_session_duration = 3600
}

# Created with the cluster, before the gateway is deployed, so its pods get
# credentials from their first start. The namespace and service account come
# from gitops/apps/pii-gateway.
resource "aws_eks_pod_identity_association" "gateway" {
  cluster_name    = module.eks.cluster_name
  namespace       = "pii-gateway"
  service_account = "pii-gateway"
  role_arn        = aws_iam_role.gateway.arn
}

output "gateway_role_arn" {
  description = "Pod Identity role used by the PII gateway."
  value       = aws_iam_role.gateway.arn
}
