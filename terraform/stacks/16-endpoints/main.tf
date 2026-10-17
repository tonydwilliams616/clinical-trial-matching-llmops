# -----------------------------------------------------------------------------
# EPHEMERAL interface endpoints - private connections from the VPC to AWS
# APIs. Traffic to these services (above all Bedrock, which receives masked
# clinical text) stays on the AWS network instead of crossing the internet via
# the NAT gateway.
#
# Each endpoint places one network interface in each private subnet and bills
# per interface-hour (~$0.01), so 6 endpoints x 3 AZs is ~$0.18/hour. Destroyed
# nightly by the Terraform Destroy workflow.
#
# With private DNS on, the normal service hostnames (bedrock-runtime.us-east-1.
# amazonaws.com, ...) resolve to the endpoint's private IPs inside the VPC, so
# SDKs need no configuration changes.
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
  vpc_id             = data.terraform_remote_state.network.outputs.vpc_id
  vpc_cidr_block     = data.terraform_remote_state.network.outputs.vpc_cidr_block
  private_subnet_ids = data.terraform_remote_state.network.outputs.private_subnet_ids
}

# HTTPS in from inside the VPC only; no egress (security groups are stateful,
# so replies are allowed without an egress rule). Phase 2 narrows the Bedrock
# endpoint further, so only the gateway can reach it.
resource "aws_security_group" "endpoints" {
  name        = "${var.project_name}-vpc-endpoints"
  description = "Interface endpoints - HTTPS from inside the VPC only"
  vpc_id      = local.vpc_id

  tags = {
    Name = "${var.project_name}-vpc-endpoints"
  }
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_https" {
  security_group_id = aws_security_group.endpoints.id
  description       = "HTTPS from the VPC"
  cidr_ipv4         = local.vpc_cidr_block
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_endpoint" "interface" {
  for_each = var.interface_endpoints

  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = local.private_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]

  tags = {
    Name = "${var.project_name}-${replace(each.key, ".", "-")}"
  }
}
