# -----------------------------------------------------------------------------
# Customer-managed KMS key for the RAW bucket only.
# Raw data contains (synthetic) identifiers, so it's treated as if it were PHI.
# With its own key, access needs BOTH s3:GetObject and kms:Decrypt - so a role
# can be kept away from raw data by never granting it this key, even if a
# bucket permission were added by mistake. ~$1/month.
# -----------------------------------------------------------------------------
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "raw_key" {
  #checkov:skip=CKV_AWS_109:Key policy - "*" resource means this key only; root principal delegates to IAM
  #checkov:skip=CKV_AWS_111:Key policy - "*" resource means this key only; root principal delegates to IAM
  #checkov:skip=CKV_AWS_356:Key policy - "*" resource means this key only; root principal delegates to IAM

  # Standard default: the account (via IAM policies) administers and uses the
  # key. Without this statement the key can become unmanageable.
  statement {
    sid       = "EnableIamPolicies"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_kms_key" "raw" {
  description             = "${var.project_name} raw data bucket - synthetic data with planted identifiers"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.raw_key.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "raw" {
  name          = "alias/${var.project_name}-raw-data"
  target_key_id = aws_kms_key.raw.key_id
}
