# -----------------------------------------------------------------------------
# DE-IDENTIFIED bucket - output of the de-identification step and its
# evaluation reports. The only data later phases (retrieval, the LLM agent)
# are allowed to read.
# Layout: <dataset>/<version>/...  plus deid-eval/<run>/ for metrics
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "deidentified" {
  #checkov:skip=CKV_AWS_144:Cross-region replication not needed - regenerable from the raw bucket
  #checkov:skip=CKV_AWS_18:Access logging deferred to the hardening backlog
  #checkov:skip=CKV2_AWS_62:Event notifications not needed
  #checkov:skip=CKV_AWS_145:Identifiers removed by design, so SSE-S3 is sufficient; the customer-managed key is reserved for raw data
  bucket = "${var.project_name}-deidentified-${data.aws_caller_identity.current.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "deidentified" {
  bucket = aws_s3_bucket.deidentified.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "deidentified" {
  bucket = aws_s3_bucket.deidentified.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "deidentified" {
  bucket = aws_s3_bucket.deidentified.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "deidentified" {
  bucket = aws_s3_bucket.deidentified.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "deidentified" {
  bucket = aws_s3_bucket.deidentified.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "deidentified_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.deidentified.arn,
      "${aws_s3_bucket.deidentified.arn}/*",
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
}

resource "aws_s3_bucket_policy" "deidentified" {
  bucket = aws_s3_bucket.deidentified.id
  policy = data.aws_iam_policy_document.deidentified_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.deidentified]
}
