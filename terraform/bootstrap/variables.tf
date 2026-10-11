variable "project_name" {
  description = "Prefix used for naming resources."
  type        = string
  default     = "ctm"
}

variable "aws_region" {
  description = "AWS region for the state bucket and all stacks."
  type        = string
  default     = "us-east-1"
}

variable "aws_account_id" {
  description = "The clinical-trial-matching account ID. The provider refuses to run against any other account."
  type        = string
  default     = "359013545044"

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Set aws_account_id to the 12-digit clinical-trial-matching account ID."
  }
}

variable "github_owner" {
  description = "GitHub user or organisation that owns the repo."
  type        = string
  default     = "tonydwilliams616"
}

variable "github_repo" {
  description = "GitHub repository name."
  type        = string
  default     = "clinical-trial-matching-llmops"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false if one already exists in this account."
  type        = bool
  default     = true
}

variable "github_owner_id" {
  description = "Immutable numeric ID of the GitHub owner, included in the OIDC sub claim."
  type        = string
  default     = "219661695"
}

variable "github_repo_id" {
  description = "Immutable numeric ID of the GitHub repo, included in the OIDC sub claim."
  type        = string
  default     = "1414399775"

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repo_id))
    error_message = "Set github_repo_id to the repo's numeric ID (gh api repos/<owner>/<repo> --jq .id)."
  }
}
