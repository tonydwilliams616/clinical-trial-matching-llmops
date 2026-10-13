output "budget_alerts_topic_arn" {
  description = "SNS topic receiving budget alerts."
  value       = module.cost_guardrails.sns_topic_arn
}

output "account_budget_name" {
  description = "Account-wide monthly budget."
  value       = module.cost_guardrails.account_budget_name
}

output "project_budget_name" {
  description = "Project-tag monthly budget."
  value       = module.cost_guardrails.project_budget_name
}
