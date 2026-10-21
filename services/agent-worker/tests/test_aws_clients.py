"""Regression test from the first EKS session: S3 must use the regional address.

The global s3.amazonaws.com resolves to public IPs, which the worker's
NetworkPolicy blocks; only s3.us-east-1.amazonaws.com goes through the VPC's
S3 interface endpoint. No credentials or network needed: this only builds
the clients and inspects their endpoints.
"""

from app.worker import aws_clients


def test_s3_and_sqs_use_regional_endpoints(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    s3, sqs = aws_clients()
    assert s3.meta.endpoint_url == "https://s3.us-east-1.amazonaws.com"
    assert "us-east-1" in sqs.meta.endpoint_url


def test_clients_fail_fast(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    s3, _ = aws_clients()
    assert s3.meta.config.connect_timeout == 5
    assert s3.meta.config.read_timeout > 20  # above SQS long polling
