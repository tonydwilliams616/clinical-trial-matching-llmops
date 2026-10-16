# -----------------------------------------------------------------------------
# CI EVALUATION role - lets the gateway's benchmark job (PR 11b) read the
# notes/v1 answer key from the raw bucket, and nothing else.
#
# Lives in this stack, next to the bucket and key it reads, so the policy can
# reference them directly. Trust: pull requests (gate before merge) and main.
# Read-only, one prefix, and the raw key only via S3 - no direct KMS use.
# -----------------------------------------------------------------------------

variable "github_oidc_subject_prefix" {
  description = "GitHub OIDC sub prefix with immutable owner/repo IDs (same as bootstrap)."
  type        = string
  default     = "repo:tonydwilliams616@219661695/clinical-trial-matching-llmops@1414399775"
}

variable "eval_dataset_prefix" {
  description = "The only raw-bucket prefix the evaluation role may read."
  type        = string
  default     = "notes/v1/"
}

# The provider itself is created in bootstrap; look it up here.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_eval_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "${var.github_oidc_subject_prefix}:pull_request",
        "${var.github_oidc_subject_prefix}:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "github_eval" {
  name                 = "${var.project_name}-github-eval"
  description          = "Assumed by GitHub Actions to read the de-identification benchmark (notes/v1) - read-only"
  assume_role_policy   = data.aws_iam_policy_document.github_eval_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "github_eval" {
  statement {
    sid       = "ListBenchmarkPrefixOnly"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.raw.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.eval_dataset_prefix}*"]
    }
  }

  statement {
    sid       = "ReadBenchmark"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.raw.arn}/${var.eval_dataset_prefix}*"]
  }

  # Objects are encrypted with the raw key, so reading needs Decrypt too.
  # ViaService: only when S3 asks on the role's behalf, never a direct KMS call.
  statement {
    sid       = "DecryptViaS3Only"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.raw.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "github_eval" {
  name   = "read-benchmark"
  role   = aws_iam_role.github_eval.id
  policy = data.aws_iam_policy_document.github_eval.json
}

output "github_eval_role_arn" {
  description = "Role for the benchmark job - store as GitHub variable AWS_EVAL_ROLE_ARN."
  value       = aws_iam_role.github_eval.arn
}
