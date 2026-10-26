# -----------------------------------------------------------------------------
# Operational alerts: Alertmanager in the cluster publishes the project's Ctm*
# alerts here, and the topic emails them (firing and resolved).
#
# Separate from the budget-alerts topic so "the platform is unhealthy" and
# "money is being spent" stay distinct, but it reuses the same alert_email
# (a sensitive variable from a GitHub secret, never in the repo or in plans).
#
# Encrypted with the AWS-managed SNS key. Its key policy lets principals in
# this account use it through SNS, so the publisher needs only sns:Publish -
# granted to Alertmanager's Pod Identity role in 20-eks, on this topic only.
# Permanent and pennies a month, so it survives the nightly teardown.
# -----------------------------------------------------------------------------
resource "aws_sns_topic" "ops_alerts" {
  name              = "${var.project_name}-ops-alerts"
  kms_master_key_id = "alias/aws/sns"
}

# Requires clicking the confirmation link AWS emails after the first apply.
resource "aws_sns_topic_subscription" "ops_alerts_email" {
  topic_arn = aws_sns_topic.ops_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

output "ops_alerts_topic_arn" {
  description = "SNS topic Alertmanager publishes Ctm* alerts to (read by 20-eks for the Pod Identity policy)."
  value       = aws_sns_topic.ops_alerts.arn
}
