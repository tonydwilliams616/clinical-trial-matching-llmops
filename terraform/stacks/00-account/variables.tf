variable "project_name" {
  description = "Prefix used for naming resources."
  type        = string
  default     = "ctm"
}

variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "aws_account_id" {
  description = "The clinical-trial-matching account ID. The provider refuses to run against any other account."
  type        = string
  default     = "359013545044"
}

variable "alert_email" {
  description = "Email address for budget and anomaly alerts. Set via TF_VAR_alert_email (GitHub secret ALERT_EMAIL)."
  type        = string
  # Sensitive so it never appears in plan output - plans are posted as
  # comments on a PUBLIC repo, and GitHub's secret masking doesn't apply there.
  sensitive = true
}
