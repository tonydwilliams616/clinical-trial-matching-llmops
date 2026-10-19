output "karpenter_node_role_name" {
  description = "IAM role for Karpenter-launched nodes - referenced by the EC2NodeClass in gitops/."
  value       = module.karpenter.node_iam_role_name
}

output "karpenter_interruption_queue" {
  description = "SQS queue receiving Spot interruption and instance state events."
  value       = module.karpenter.queue_name
}

output "external_secrets_role_arn" {
  description = "Pod Identity role used by External Secrets Operator."
  value       = aws_iam_role.external_secrets.arn
}

output "argocd_ui_command" {
  description = "Open the Argo CD UI at http://localhost:8080 (admin password: see argocd_password_command)."
  value       = "kubectl -n argocd port-forward svc/argocd-server 8080:80"
}

output "argocd_password_command" {
  description = "Print the initial Argo CD admin password."
  value       = "kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
}
