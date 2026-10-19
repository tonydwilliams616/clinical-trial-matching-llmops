terraform {
  required_version = ">= 1.10" # S3 native state locking (use_lockfile)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Refuse to run against any other account, whatever credentials are active.
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project    = var.project_name
      ManagedBy  = "terraform"
      Stack      = "30-platform"
      Repository = "tonydwilliams616/clinical-trial-matching-llmops"
    }
  }
}

# Karpenter's charts live in ECR Public; authenticated pulls avoid rate limits
# on shared GitHub runner IPs. ECR Public auth only works in us-east-1.
data "aws_ecrpublic_authorization_token" "token" {}

# Authenticates to EKS with a short-lived token from whichever AWS identity is
# running Terraform (CI plan/apply role, or you locally) - no stored kubeconfig.
provider "helm" {
  kubernetes = {
    host                   = local.cluster_endpoint
    cluster_ca_certificate = base64decode(local.cluster_ca)

    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", local.cluster_name, "--region", var.aws_region]
    }
  }

  registries = [
    {
      url      = "oci://public.ecr.aws"
      username = data.aws_ecrpublic_authorization_token.token.user_name
      password = data.aws_ecrpublic_authorization_token.token.password
    }
  ]
}
