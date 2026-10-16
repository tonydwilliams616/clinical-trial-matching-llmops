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

variable "vpc_cidr" {
  description = "CIDR block for the VPC. Not 10.0.0.0/16, to leave room for peering or VPN without overlaps."
  type        = string
  default     = "10.20.0.0/16"
}

variable "az_ids" {
  # Zone IDs are the same physical zones in every account (names like
  # us-east-1a are shuffled per account), and a fixed list never grows when
  # AWS adds a zone. use1-az3 is avoided: it does not support EKS control planes.
  description = "Availability zones by zone ID, pinned."
  type        = list(string)
  default     = ["use1-az1", "use1-az2", "use1-az4"]

  validation {
    condition     = length(var.az_ids) >= 2 && length(var.az_ids) <= 3 && alltrue([for id in var.az_ids : can(regex("^use1-az[0-9]+$", id))])
    error_message = "Use 2 or 3 us-east-1 zone IDs (e.g. use1-az1); EKS needs at least 2 and this layout supports up to 3."
  }

  validation {
    condition     = !contains(var.az_ids, "use1-az3")
    error_message = "use1-az3 does not support EKS control planes."
  }
}

variable "cluster_name" {
  description = "EKS cluster name - used in Karpenter subnet discovery tags. Must match the 20-eks stack and the destroy workflow."
  type        = string
  default     = "ctm-eks"
}
