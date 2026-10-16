output "vpc_id" {
  description = "VPC ID - also read by the destroy workflow for network-interface clean-up."
  value       = module.vpc.vpc_id
}

output "vpc_cidr_block" {
  description = "VPC CIDR block - for security group rules in later stacks."
  value       = module.vpc.vpc_cidr_block
}

output "az_ids" {
  description = "Availability zone IDs in use."
  value       = var.az_ids
}

output "private_subnet_ids" {
  description = "Private subnet IDs (EKS nodes, pods, interface endpoints)."
  value       = module.vpc.private_subnets
}

output "public_subnet_ids" {
  description = "Public subnet IDs (load balancers, NAT gateway)."
  value       = module.vpc.public_subnets
}

output "private_route_table_ids" {
  description = "Private route table IDs - 15-nat adds the default route via the NAT gateway here."
  value       = module.vpc.private_route_table_ids
}

output "cluster_name" {
  description = "Cluster name used in discovery tags - consumed by 20-eks."
  value       = var.cluster_name
}
