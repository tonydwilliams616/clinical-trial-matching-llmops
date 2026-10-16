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

variable "az_count" {
  description = "Number of availability zones to spread subnets across."
  type        = number
  default     = 3

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "EKS needs at least 2 AZs; this layout supports up to 3."
  }
}

variable "cluster_name" {
  description = "EKS cluster name - used in Karpenter subnet discovery tags. Must match the 20-eks stack and the destroy workflow."
  type        = string
  default     = "ctm-eks"
}
