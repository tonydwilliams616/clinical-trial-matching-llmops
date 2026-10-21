"""
Regression tests from the phase 3 EKS session: emails went unmasked on the
cluster because tldextract (used by Presidio to validate email endings) tried
to download the public suffix list, the NetworkPolicy silently dropped it,
and the hung download held a lock that broke every later email check.
"""

import socket

import pytest
import tldextract.tldextract
from fastapi.testclient import TestClient

import app.masker  # noqa: F401 - importing it applies the offline setting
from app.main import app, self_test


def test_email_validation_is_configured_offline():
    # No URLs = bundled suffix list only: nothing is ever downloaded
    assert tldextract.tldextract.TLD_EXTRACTOR.suffix_list_urls == ()


def test_email_masked_without_any_network(monkeypatch):
    attempts = []

    def no_network(*args, **kwargs):
        attempts.append(args)
        raise OSError("network disabled in this test")
    monkeypatch.setattr(socket, "create_connection", no_network)
    with TestClient(app) as client:
        body = client.post("/v1/mask", json={"text": "Contact: email rjacobs33@example.com."}).json()
    assert "<EMAIL>" in body["masked_text"]
    assert "rjacobs33" not in body["masked_text"]
    assert attempts == []


class BrokenMasker:
    """Masks nothing - as the gateway did on EKS with emails."""

    def mask(self, text):
        return {"masked_text": text, "findings": [], "counts": {}}


def test_start_up_self_test_refuses_a_broken_masker():
    with pytest.raises(RuntimeError, match="self-test failed"):
        self_test(BrokenMasker())
