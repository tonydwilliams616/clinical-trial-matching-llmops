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

variable "interface_endpoints" {
  description = "AWS services reached through interface endpoints (suffix after com.amazonaws.<region>.)."
  type        = set(string)
  default = [
    "bedrock-runtime", # model calls from the PII gateway (phase 3)
    "ecr.api",         # image metadata and auth for node image pulls
    "ecr.dkr",         # image manifests (layers come via the free S3 gateway endpoint)
    "sts",             # credentials for Pod Identity / role assumption
    "sqs",             # agent-worker job queue (phase 3)
    "logs",            # CloudWatch Logs from the cluster
  ]
}
