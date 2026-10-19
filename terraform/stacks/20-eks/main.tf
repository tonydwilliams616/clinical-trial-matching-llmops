# -----------------------------------------------------------------------------
# EPHEMERAL EKS cluster - destroyed nightly by the Terraform Destroy workflow.
# Control plane ~$0.10/h plus two small Spot system nodes. Workload nodes come
# later from Karpenter (30-platform); the managed node group here only runs
# cluster add-ons and platform controllers.
#
# Needs 15-nat (and ideally 16-endpoints) up: nodes in private subnets pull
# add-on images and call AWS APIs during bootstrap.
# -----------------------------------------------------------------------------
data "aws_caller_identity" "current" {}

locals {
  # CI roles named explicitly, so access never depends on who runs Terraform
  plan_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-github-plan"
  apply_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-github-apply"
}

module "eks" {
  # Pinned to the commit of release v21.26.0: a commit hash cannot be re-pointed.
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-eks.git?ref=323c633629b8e4306d94eb1392d7400a80143621"

  name               = local.cluster_name
  kubernetes_version = var.kubernetes_version

  vpc_id     = local.vpc_id
  subnet_ids = local.private_subnet_ids

  # Public endpoint so GitHub Actions and your laptop can reach the API (every
  # call still needs IAM auth); private endpoint so nodes stay inside the VPC.
  endpoint_public_access  = true
  endpoint_private_access = true

  # Access entries only - no aws-auth ConfigMap to drift or get corrupted
  authentication_mode = "API"

  # No implicit admin for whoever happens to create the cluster: every admin
  # is listed explicitly below.
  enable_cluster_creator_admin_permissions = false

  access_entries = merge(
    # Humans with cluster-admin
    {
      for name, arn in var.admin_principal_arns : name => {
        principal_arn = arn
        policy_associations = {
          admin = {
            policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
    },
    {
      # CI plan role: read-only, but including Secrets, because Helm keeps
      # release state in Secrets and must read it to plan 30-platform.
      ci-plan = {
        principal_arn = local.plan_role_arn
        policy_associations = {
          view = {
            policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSAdminViewPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
      # CI apply role: cluster-admin, to install the platform Helm charts
      ci-apply = {
        principal_arn = local.apply_role_arn
        policy_associations = {
          admin = {
            policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
    }
  )

  # EKS Pod Identity instead of IRSA: no OIDC provider per cluster, simpler
  # trust policies, and role associations survive cluster re-creation.
  enable_irsa = false

  addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent    = true
      before_compute = true # networking must exist before nodes join
    }
    eks-pod-identity-agent = {
      most_recent    = true
      before_compute = true
    }
    metrics-server = {
      most_recent = true # CPU/memory metrics for HPA
    }
  }

  # EKS already envelope-encrypts Kubernetes secrets at rest with an
  # AWS-owned key. A customer-managed key would be created (and billed) on
  # every spin-up of an ephemeral cluster.
  create_kms_key    = false
  encryption_config = null

  # Control-plane logs off for now: on an ephemeral cluster EKS can re-create
  # the log group after Terraform deletes it, breaking the next apply. Planned
  # follow-up: a permanent, retention-capped log group for audit logs.
  create_cloudwatch_log_group = false
  enabled_log_types           = []

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = var.system_node_instance_types
      capacity_type  = "SPOT" # ~70% cheaper; fine for a session-only cluster

      min_size     = 2
      max_size     = 3
      desired_size = 2

      labels = {
        "node-role" = "system"
      }
    }
  }

  # Karpenter finds the node security group by this tag (30-platform)
  node_security_group_tags = {
    "karpenter.sh/discovery" = local.cluster_name
  }
}
