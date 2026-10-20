# -----------------------------------------------------------------------------
# S3 interface endpoint - so S3 traffic from pods uses PRIVATE VPC addresses.
#
# The free S3 gateway endpoint (10-network) keeps S3 traffic off the internet,
# but clients still connect to S3's public IP ranges. A NetworkPolicy can't
# allow "S3" by name, only by address range, so workloads that may only send
# HTTPS inside the VPC (10.20.0.0/16) couldn't reach S3 through it.
#
# With this endpoint, S3 hostnames resolve to endpoint IPs inside the VPC.
# One setting matters: "private DNS only for inbound resolver endpoint"
# defaults to TRUE when a gateway endpoint exists, which keeps in-VPC traffic
# on the gateway endpoint (public IPs). It is set to FALSE here so in-VPC
# traffic uses this endpoint. The gateway endpoint must still exist for this
# setting to be allowed.
#
# Cost: ~$0.01 per interface-hour x 3 AZs while the cluster is up, plus
# $0.01/GB processed (image layers, datasets). Destroyed nightly with the rest
# of this stack.
# -----------------------------------------------------------------------------
resource "aws_vpc_endpoint" "s3_interface" {
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = local.private_subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]

  dns_options {
    dns_record_ip_type                             = "ipv4"
    private_dns_only_for_inbound_resolver_endpoint = false
  }

  tags = {
    Name = "${var.project_name}-s3-interface"
  }
}

output "s3_interface_endpoint_id" {
  description = "S3 interface endpoint - S3 resolves to private VPC addresses."
  value       = aws_vpc_endpoint.s3_interface.id
}
