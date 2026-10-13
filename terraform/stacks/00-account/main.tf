# -----------------------------------------------------------------------------
# Account guardrails - permanent stack, applied before anything that can spend.
# -----------------------------------------------------------------------------
module "cost_guardrails" {
  source = "../../modules/cost-guardrails"

  project_name = var.project_name
  alert_email  = var.alert_email

  # Account-wide budget, plus a budget for resources tagged Project=ctm.
  monthly_budget_limit = 30
  project_budget_limit = 25
  project_tag_value    = var.project_name

  # The Project tag only shows up in billing data ~24h after the first tagged
  # resource; activate it in a follow-up PR. Until then the project budget reads $0.
  activate_cost_allocation_tag = false

  enable_anomaly_detection = true
  anomaly_threshold_usd    = 10
}
