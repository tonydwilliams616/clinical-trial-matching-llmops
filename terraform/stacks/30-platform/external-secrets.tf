# -----------------------------------------------------------------------------
# External Secrets Operator - AWS side only. Argo CD installs the operator
# (gitops/bootstrap/external-secrets.yaml); this gives it a Pod Identity role
# that can read secrets named ctm/* from Secrets Manager, and nothing else.
# -----------------------------------------------------------------------------
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "eso_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "external_secrets" {
  name                 = "${var.project_name}-external-secrets"
  description          = "Pod Identity role for External Secrets Operator - read ctm/* secrets only"
  assume_role_policy   = data.aws_iam_policy_document.eso_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "eso_read" {
  statement {
    sid = "ReadProjectSecrets"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/*"]
  }
}

resource "aws_iam_role_policy" "external_secrets" {
  name   = "read-project-secrets"
  role   = aws_iam_role.external_secrets.id
  policy = data.aws_iam_policy_document.eso_read.json
}

# Binds the role to the operator's service account. Exists before the
# operator is installed, so its pods get credentials from their first start.
resource "aws_eks_pod_identity_association" "external_secrets" {
  cluster_name    = local.cluster_name
  namespace       = "external-secrets"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.external_secrets.arn
}
