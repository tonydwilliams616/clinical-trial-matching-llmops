output "state_bucket_name" {
  description = "S3 bucket holding Terraform state for all stacks."
  value       = aws_s3_bucket.tfstate.id
}

output "github_plan_role_arn" {
  description = "Role for terraform plan on pull requests - store as GitHub variable AWS_PLAN_ROLE_ARN."
  value       = aws_iam_role.github_plan.arn
}

output "github_apply_role_arn" {
  description = "Role for terraform apply from the production environment - store as GitHub variable AWS_APPLY_ROLE_ARN."
  value       = aws_iam_role.github_apply.arn
}

output "github_ecr_push_role_arn" {
  description = "Role for pushing images from main - store as GitHub variable AWS_ECR_PUSH_ROLE_ARN."
  value       = aws_iam_role.github_ecr_push.arn
}

output "backend_config_example" {
  description = "Backend block to use in each stack (change the key per stack)."
  value       = <<-EOT
    backend "s3" {
      bucket       = "${aws_s3_bucket.tfstate.id}"
      key          = "<stack-name>/terraform.tfstate"
      region       = "${var.aws_region}"
      encrypt      = true
      use_lockfile = true
    }
  EOT
}
