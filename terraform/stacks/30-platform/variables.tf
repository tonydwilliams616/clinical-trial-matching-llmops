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

variable "karpenter_version" {
  description = "Karpenter chart version. Kubernetes 1.36 needs Karpenter >= 1.13 (karpenter.sh compatibility matrix)."
  type        = string
  default     = "1.14.1"
}

variable "argocd_chart_version" {
  description = "argo-cd Helm chart version (10.9.6 = Argo CD v3.5.x)."
  type        = string
  default     = "10.9.6"
}

variable "argocd_apps_chart_version" {
  description = "argocd-apps Helm chart version, used only to create the root Application."
  type        = string
  default     = "2.0.6"
}

variable "gitops_repo_url" {
  description = "Git repository Argo CD syncs from (public, so no credentials needed)."
  type        = string
  default     = "https://github.com/tonydwilliams616/clinical-trial-matching-llmops.git"
}
