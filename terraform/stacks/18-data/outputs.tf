output "raw_bucket_name" {
  description = "Bucket for raw synthetic data (with planted identifiers)."
  value       = aws_s3_bucket.raw.id
}

output "raw_bucket_arn" {
  description = "ARN of the raw data bucket - for IAM policies in later stacks."
  value       = aws_s3_bucket.raw.arn
}

output "raw_kms_key_arn" {
  description = "KMS key protecting raw data - only roles granted this key can read it."
  value       = aws_kms_key.raw.arn
}

output "deidentified_bucket_name" {
  description = "Bucket for de-identified data and evaluation reports."
  value       = aws_s3_bucket.deidentified.id
}

output "deidentified_bucket_arn" {
  description = "ARN of the de-identified bucket - for IAM policies in later stacks."
  value       = aws_s3_bucket.deidentified.arn
}
