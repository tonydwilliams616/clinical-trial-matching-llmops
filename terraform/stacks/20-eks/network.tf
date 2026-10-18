# VPC, subnets and the cluster name come from the permanent 10-network stack.
data "terraform_remote_state" "network" {
  backend = "s3"

  config = {
    bucket = "ctm-tfstate-${var.aws_account_id}"
    key    = "10-network/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  cluster_name       = data.terraform_remote_state.network.outputs.cluster_name
  vpc_id             = data.terraform_remote_state.network.outputs.vpc_id
  private_subnet_ids = data.terraform_remote_state.network.outputs.private_subnet_ids
}
