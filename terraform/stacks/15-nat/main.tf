# -----------------------------------------------------------------------------
# EPHEMERAL NAT gateway - outbound internet for the private subnets, needed
# for things that have no VPC endpoint (public container images, Helm charts).
# Billed by the hour (~$0.045/h + public IPv4 ~$0.005/h + data), so it is
# destroyed every night by the Terraform Destroy workflow. The VPC itself
# (10-network) is permanent.
# -----------------------------------------------------------------------------

data "terraform_remote_state" "network" {
  backend = "s3"

  config = {
    bucket = "ctm-tfstate-${var.aws_account_id}"
    key    = "10-network/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  public_subnet_id        = data.terraform_remote_state.network.outputs.public_subnet_ids[0]
  private_route_table_ids = data.terraform_remote_state.network.outputs.private_route_table_ids
}

resource "aws_eip" "nat" {
  #checkov:skip=CKV2_AWS_19:This EIP is attached to the NAT gateway below, not to an EC2 instance
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-nat"
  }
}

# One NAT gateway in the first public subnet: cost over resilience. If its AZ
# fails, private subnets lose internet until the next apply - acceptable for a
# stack that only exists during working sessions.
resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = local.public_subnet_id

  tags = {
    Name = "${var.project_name}-nat"
  }
}

# Default route for the private subnets: internet-bound traffic goes via the
# NAT. Destroying this stack removes the route, so private subnets lose
# internet access - nothing else changes.
resource "aws_route" "private_default" {
  count = length(local.private_route_table_ids)

  route_table_id         = local.private_route_table_ids[count.index]
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}
