# Cluster details come from the ephemeral 20-eks stack - the cluster must be up
# for this stack to plan or apply.
data "terraform_remote_state" "eks" {
  backend = "s3"

  config = {
    bucket = "ctm-tfstate-${var.aws_account_id}"
    key    = "20-eks/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  cluster_name     = data.terraform_remote_state.eks.outputs.cluster_name
  cluster_endpoint = data.terraform_remote_state.eks.outputs.cluster_endpoint
  cluster_ca       = data.terraform_remote_state.eks.outputs.cluster_certificate_authority_data

  # Platform controllers run on the managed system nodes, never on nodes
  # Karpenter manages (they would be removing their own host).
  system_node_selector = { "node-role" = "system" }
}
