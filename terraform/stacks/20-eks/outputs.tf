output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API endpoint."
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64 cluster CA - used by the Kubernetes and Helm providers in 30-platform."
  value       = module.eks.cluster_certificate_authority_data
}

output "cluster_version" {
  description = "Kubernetes version."
  value       = module.eks.cluster_version
}

output "node_security_group_id" {
  description = "Node security group (tagged for Karpenter discovery)."
  value       = module.eks.node_security_group_id
}

output "cluster_security_group_id" {
  description = "Cluster security group."
  value       = module.eks.cluster_security_group_id
}

output "kubeconfig_command" {
  description = "Run this to point kubectl at the cluster."
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region}"
}
