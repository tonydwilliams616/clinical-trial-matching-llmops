# -----------------------------------------------------------------------------
# Bedrock access for the PII gateway - the only workload that ever calls a
# model, and only with text it has already masked.
#
# Two rights, nothing else:
#   1. invoke the project's own inference profile (18-data)
#   2. invoke the underlying model in each region the profile routes to, but
#      ONLY when the call comes through that profile
#
# Both come from 18-data's outputs, so changing the model there updates this
# policy on the next apply. No streaming permission: the gateway doesn't stream.
# -----------------------------------------------------------------------------
data "terraform_remote_state" "data" {
  backend = "s3"

  config = {
    bucket = "ctm-tfstate-${var.aws_account_id}"
    key    = "18-data/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  bedrock_profile_arn        = data.terraform_remote_state.data.outputs.bedrock_profile_arn
  bedrock_profile_model_arns = data.terraform_remote_state.data.outputs.bedrock_profile_model_arns
}

data "aws_iam_policy_document" "gateway_bedrock" {
  statement {
    sid       = "InvokeProjectProfile"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.bedrock_profile_arn]
  }

  # Without this, the profile alone is refused: Bedrock also checks the model
  # in whichever region serves the request
  statement {
    sid       = "InvokeModelOnlyThroughProfile"
    actions   = ["bedrock:InvokeModel"]
    resources = local.bedrock_profile_model_arns

    condition {
      test     = "StringEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.bedrock_profile_arn]
    }
  }
}

resource "aws_iam_role_policy" "gateway_bedrock" {
  name   = "invoke-project-model"
  role   = aws_iam_role.gateway.id
  policy = data.aws_iam_policy_document.gateway_bedrock.json
}
