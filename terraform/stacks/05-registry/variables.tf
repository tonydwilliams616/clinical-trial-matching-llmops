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

variable "repositories" {
  description = "Image repositories to create, under the <project_name>/ prefix the CI push role is scoped to."
  type        = set(string)
  default = [
    "pii-gateway",  # the only workload allowed to call Bedrock
    "agent-worker", # SQS consumers that build shortlists
  ]
}

variable "images_to_keep" {
  description = "Tagged images kept per repository; older ones expire."
  type        = number
  default     = 5
}
