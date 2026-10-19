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

variable "kubernetes_version" {
  description = "EKS Kubernetes version. Must be in STANDARD support - extended support costs 6x more per hour."
  type        = string
  default     = "1.36"
}

variable "admin_principal_arns" {
  description = "IAM principal ARNs (users or roles) given cluster-admin, keyed by a short name."
  type        = map(string)
  default = {
    anthony = "arn:aws:iam::359013545044:user/terraform"
  }
}

variable "system_node_instance_types" {
  description = "Instance types for the system node group. Several similar types improve Spot availability."
  type        = list(string)
  default     = ["m5.large", "m5a.large", "m6i.large", "m6a.large", "m7i.large"]
}
