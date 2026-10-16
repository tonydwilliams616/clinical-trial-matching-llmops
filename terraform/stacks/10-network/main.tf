# -----------------------------------------------------------------------------
# PERMANENT network: VPC, subnets, route tables, internet gateway and the S3
# gateway endpoint. None of these bill by the hour, so the stack stays up.
#
# Hourly-billed networking lives in ephemeral stacks, destroyed nightly:
#   15-nat        NAT gateway (outbound internet for private subnets)
#   16-endpoints  interface endpoints (Bedrock, ECR, STS, SQS, Logs)
# -----------------------------------------------------------------------------

locals {
  # /19 private subnets (8,190 IPs each) - EKS gives every pod a VPC IP.
  # 10.20.0.0/19, 10.20.32.0/19, 10.20.64.0/19
  private_subnets = [for i, az in var.az_ids : cidrsubnet(var.vpc_cidr, 3, i)]

  # /24 public subnets - load balancers and the NAT gateway only, no workloads.
  # 10.20.96.0/24, 10.20.97.0/24, 10.20.98.0/24
  public_subnets = [for i, az in var.az_ids : cidrsubnet(var.vpc_cidr, 8, 96 + i)]
}

module "vpc" {
  # Pinned to the commit of release v6.7.3, not a version range: a git tag or
  # registry version can be re-pointed, a commit hash cannot (supply chain).
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref=b3abd6df2ecf052451a361ed55b8f06f8742a795"

  name = "${var.project_name}-vpc"
  cidr = var.vpc_cidr
  azs  = var.az_ids # zone IDs - the module places subnets by ID

  private_subnets = local.private_subnets
  public_subnets  = local.public_subnets

  # No NAT here - see 15-nat. single_nat_gateway = true still matters: it makes
  # the module create ONE shared private route table, which 15-nat adds its
  # default route to.
  enable_nat_gateway     = false
  single_nat_gateway     = true
  one_nat_gateway_per_az = false

  # Required for interface endpoints' private DNS (16-endpoints)
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Lock down the default security group: no rules, so nothing can use it
  manage_default_security_group  = true
  default_security_group_ingress = []
  default_security_group_egress  = []

  # Public subnets never give instances public IPs automatically
  map_public_ip_on_launch = false

  # Lets the AWS Load Balancer Controller place internet-facing LBs here
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }

  # Internal LBs + Karpenter node placement
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
    "karpenter.sh/discovery"          = var.cluster_name
  }
}

# Free gateway endpoint: S3 traffic (including ECR image layers, which are
# served from S3, and our data buckets) stays on the AWS network instead of
# going through the NAT gateway and its data charges.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat(module.vpc.private_route_table_ids, module.vpc.public_route_table_ids)

  tags = {
    Name = "${var.project_name}-s3-endpoint"
  }
}
