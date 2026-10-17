# -----------------------------------------------------------------------------
# VPC Flow Logs - a record of every connection in and out of the network
# (source, destination, port, accept/reject). An audit control: if something
# ever reached somewhere it shouldn't, this is where it shows up.
#
# Written to S3 as compressed Parquet, partitioned by hour (queryable with
# Athena). A lifecycle policy deletes everything after var.flow_log_retention_days,
# so storage can never build up. Traffic only exists while the ephemeral stacks
# are up, so between sessions there is next to nothing to store.
# -----------------------------------------------------------------------------

variable "flow_log_retention_days" {
  description = "Days to keep flow log files before the lifecycle policy deletes them."
  type        = number
  default     = 30

  validation {
    condition     = var.flow_log_retention_days >= 1 && var.flow_log_retention_days <= 365
    error_message = "Keep flow logs between 1 and 365 days."
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
}

resource "aws_s3_bucket" "flow_logs" {
  #checkov:skip=CKV_AWS_18:This bucket holds access-type logs itself; logging it to another bucket adds cost without audit value here
  #checkov:skip=CKV_AWS_144:Cross-region replication not needed - logs are short-lived (30 days) operational data
  #checkov:skip=CKV2_AWS_62:Event notifications not needed
  #checkov:skip=CKV_AWS_145:SSE-S3 is sufficient for network metadata; avoids KMS key policy for the log delivery service and per-request cost
  bucket = "${var.project_name}-flow-logs-${local.account_id}"
}

# Versioning stops logs being silently overwritten or deleted; the lifecycle
# policy below still removes old versions after a day, so it costs nothing extra.
resource "aws_s3_bucket_versioning" "flow_logs" {
  bucket = aws_s3_bucket.flow_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "flow_logs" {
  bucket = aws_s3_bucket.flow_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "flow_logs" {
  bucket = aws_s3_bucket.flow_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "flow_logs" {
  bucket = aws_s3_bucket.flow_logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "flow_logs" {
  bucket = aws_s3_bucket.flow_logs.id

  # The cost cap: no log file outlives the retention period
  rule {
    id     = "expire-flow-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.flow_log_retention_days
    }

    # Versioning keeps a copy when a file expires - remove it a day later
    noncurrent_version_expiration {
      noncurrent_days = 1
    }

    # Half-finished uploads are billed but never show up as objects
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  # Tidy up the delete markers left once all versions of a file are gone
  rule {
    id     = "remove-expired-delete-markers"
    status = "Enabled"

    filter {}

    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.flow_logs]
}

# Only the AWS log delivery service may write, only for flow logs from this
# account, and only over TLS.
data "aws_iam_policy_document" "flow_logs_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.flow_logs.arn,
      "${aws_s3_bucket.flow_logs.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Two key layouts: the classic AWSLogs/<account>/... and, because the flow
  # log uses Hive-compatible partitions, AWSLogs/aws-account-id=<account>/...
  # Allowing only the first caused "Access error" on delivery.
  statement {
    sid     = "AWSLogDeliveryWrite"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.flow_logs.arn}/AWSLogs/${local.account_id}/*",
      "${aws_s3_bucket.flow_logs.arn}/AWSLogs/aws-account-id=${local.account_id}/*",
    ]

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:logs:${var.aws_region}:${local.account_id}:*"]
    }
  }

  statement {
    sid       = "AWSLogDeliveryCheck"
    actions   = ["s3:GetBucketAcl", "s3:ListBucket"]
    resources = [aws_s3_bucket.flow_logs.arn]

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:logs:${var.aws_region}:${local.account_id}:*"]
    }
  }
}

resource "aws_s3_bucket_policy" "flow_logs" {
  bucket = aws_s3_bucket.flow_logs.id
  policy = data.aws_iam_policy_document.flow_logs_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.flow_logs]
}

resource "aws_flow_log" "vpc" {
  vpc_id               = module.vpc.vpc_id
  traffic_type         = "ALL" # accepted and rejected connections
  log_destination_type = "s3"
  log_destination      = aws_s3_bucket.flow_logs.arn

  # 10 minutes: the default and the cheapest aggregation
  max_aggregation_interval = 600

  destination_options {
    file_format                = "parquet"
    hive_compatible_partitions = true
    per_hour_partition         = true
  }

  tags = {
    Name = "${var.project_name}-vpc-flow-logs"
  }

  depends_on = [aws_s3_bucket_policy.flow_logs]

  # AWS checks delivery permissions when a flow log is created, and the status
  # only updates on the next delivery. Re-creating the flow log whenever the
  # bucket policy changes gives an immediate, fresh permission check.
  lifecycle {
    replace_triggered_by = [aws_s3_bucket_policy.flow_logs]
  }
}

output "flow_logs_bucket_name" {
  description = "Bucket holding VPC flow logs (deleted after the retention period)."
  value       = aws_s3_bucket.flow_logs.id
}
