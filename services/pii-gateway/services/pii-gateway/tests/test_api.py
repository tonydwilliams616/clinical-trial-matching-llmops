"""
End-to-end checks through the real API with the real model loaded.

These are smoke tests (does masking work at all?), not the accuracy
measurement - that is the benchmark gate in PR 11.
All values below are fake: 555-01xx phones, example.com email, 999 SSN.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import MAX_TEXT_CHARS, app

NOTE = (
    "Patient: John Smith    MRN 4821937\n"
    "Patient contact: (617) 555-0147, email john.s42@example.com.\n"
    "Insurance verification: SSN 999-52-8841.\n"
    "Plan: Continue current treatment."
)
IDENTIFIERS = ["John", "Smith", "4821937", "555-0147", "john.s42@example.com", "999-52-8841"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # "with" runs start-up, which loads the model
        yield c


def test_health_and_ready(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["status"] == "ready"


def test_identifiers_are_masked(client):
    body = client.post("/v1/mask", json={"text": NOTE}).json()
    for value in IDENTIFIERS:
        assert value not in body["masked_text"], value
    for label in ["PERSON", "MRN", "PHONE", "EMAIL", "SSN"]:
        assert f"<{label}>" in body["masked_text"], label
    assert "Continue current treatment." in body["masked_text"]


def test_response_never_echoes_values(client):
    raw = json.dumps(client.post("/v1/mask", json={"text": NOTE}).json())
    for value in IDENTIFIERS:
        assert value not in raw, value


def test_no_phantom_findings_inside_a_phone(client):
    # Regression: the phone's last 7 digits were also reported as an MRN
    text = "Seen John Smith, MRN 4821937, phone (617) 555-0147."
    body = client.post("/v1/mask", json={"text": text}).json()
    assert body["counts"] == {"PERSON": 1, "MRN": 1, "PHONE": 1}
    spans = [(f["start"], f["end"]) for f in body["findings"]]
    for i, (s1, e1) in enumerate(spans):
        for j, (s2, e2) in enumerate(spans):
            assert i == j or not (s2 <= s1 and e1 <= e2), "nested finding"


def test_hyphenated_mrn_needs_record_context(client):
    body = client.post("/v1/mask", json={"text": "See record no. 482-1937 for details."}).json()
    assert body["counts"].get("MRN") == 1


def test_clinical_text_left_alone(client):
    text = "Continue metformin and review blood pressure."
    body = client.post("/v1/mask", json={"text": text}).json()
    assert body["masked_text"] == text
    assert body["findings"] == []


@pytest.mark.parametrize("text", ["", "x" * (MAX_TEXT_CHARS + 1)])
def test_rejects_empty_and_oversized(client, text):
    assert client.post("/v1/mask", json={"text": text}).status_code == 422
