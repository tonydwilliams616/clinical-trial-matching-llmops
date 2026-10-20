# -----------------------------------------------------------------------------
# Bedrock as code: the project's own application inference profile.
#
# A named entry point to one model, copied from AWS's US cross-region profile:
#   - Bedrock usage carries this stack's tags (Project = ctm), so model spend
#     can be tracked per project
#   - IAM can allow THIS profile only (20-eks grants it to the PII gateway),
#     rather than any model in the account
#   - US-only routing keeps masked text inside US regions
#
# Free to keep: Bedrock bills per token used, not for the profile.
# Changing the model is a one-line change to the variable below.
# -----------------------------------------------------------------------------
variable "bedrock_source_profile_id" {
  description = "System-defined (cross-region) inference profile that the project's profile copies its model and regions from."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

resource "aws_bedrock_inference_profile" "matching" {
  name        = "${var.project_name}-matching"
  description = "Clinical trial matching on masked clinical notes"

  model_source {
    copy_from = "arn:aws:bedrock:${var.aws_region}:${var.aws_account_id}:inference-profile/${var.bedrock_source_profile_id}"
  }
}

output "bedrock_profile_arn" {
  description = "ARN of the project's inference profile - the gateway calls Bedrock with this as the model ID."
  value       = aws_bedrock_inference_profile.matching.arn
}

output "bedrock_profile_model_arns" {
  description = "Foundation model ARNs in every region the profile can route to - IAM must allow each one."
  value       = aws_bedrock_inference_profile.matching.models[*].model_arn
}
