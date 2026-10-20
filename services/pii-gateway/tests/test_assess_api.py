"""
/v1/assess through the real API, with the real masking model loaded and a
fake Bedrock client in place of the real one (no network, no cost).

What matters most here is the order of operations: the model must only ever
see masked text, and a failed check must mean nothing is sent at all.
All values are fake: 555-01xx phones, example.com email, 999 SSN.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.assess import bedrock_dependency
from app.main import app, engine

NOTE = (
    "Patient: John Smith    MRN 4821937\n"
    "Patient contact: (617) 555-0147, email john.s42@example.com.\n"
    "History: hypertension, well controlled on lisinopril. BP 128/82 today."
)
IDENTIFIERS = ["John", "Smith", "4821937", "555-0147", "john.s42@example.com"]
CRITERION = "No history of uncontrolled hypertension"
PROFILE = "arn:aws:bedrock:us-east-1:111111111111:application-inference-profile/test"


class FakeBedrock:
    """Stands in for the boto3 bedrock-runtime client and records every call."""

    def __init__(self, reply='{"verdict": "likely_meets", "reason": "Hypertension is well controlled."}',
                 error=None):
        self.reply, self.error, self.calls = reply, error, []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"output": {"message": {"content": [{"text": self.reply}]}},
                "usage": {"inputTokens": 120, "outputTokens": 30}}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # "with" runs start-up, which loads the model
        yield c


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", PROFILE)
    bedrock = FakeBedrock()
    app.dependency_overrides[bedrock_dependency] = lambda: bedrock
    yield bedrock
    app.dependency_overrides.clear()


def post(client, note=NOTE, criterion=CRITERION):
    return client.post("/v1/assess", json={"note": note, "criterion": criterion})


def test_model_only_sees_masked_text(client, fake):
    response = post(client)
    assert response.status_code == 200
    assert response.json()["verdict"] == "likely_meets"

    assert len(fake.calls) == 1
    sent = json.dumps(fake.calls[0])
    for value in IDENTIFIERS:
        assert value not in sent, value
    assert "<PERSON>" in sent and "<PHONE>" in sent
    assert fake.calls[0]["modelId"] == PROFILE
    assert fake.calls[0]["inferenceConfig"]["temperature"] == 0


def test_response_reports_counts_never_values(client, fake):
    raw = post(client).text
    for value in IDENTIFIERS:
        assert value not in raw, value
    assert json.loads(raw)["counts"]["PERSON"] >= 1


def test_unreadable_reply_becomes_unclear(client, fake):
    fake.reply = "The patient is probably fine."
    body = post(client).json()
    assert body["verdict"] == "unclear"


def test_masking_miss_means_nothing_is_sent(client, fake, monkeypatch):
    # Simulate the masker missing everything: the independent check must stop it
    monkeypatch.setattr(engine["masker"], "mask",
                        lambda text: {"masked_text": text, "findings": [], "counts": {}})
    response = post(client)
    assert response.status_code == 422
    assert fake.calls == []


def test_identifier_in_criterion_means_nothing_is_sent(client, fake):
    response = post(client, criterion="Patient reachable at (617) 555-0147")
    assert response.status_code == 422
    assert fake.calls == []


def test_model_failure_is_502_without_details(client, fake):
    fake.error = RuntimeError("AccessDenied for arn:aws:iam::secret")
    response = post(client)
    assert response.status_code == 502
    assert "secret" not in response.text and "AccessDenied" not in response.text


def test_not_configured_is_503(client, monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    assert post(client).status_code == 503
