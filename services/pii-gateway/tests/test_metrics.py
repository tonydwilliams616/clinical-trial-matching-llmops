"""Gateway metrics: the right numbers move, labels stay bounded, no text leaks."""

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.assess import bedrock_dependency
from app.main import app

NOTE = "Seen John Smith, MRN 4821937, phone (617) 555-0147. BP 128/82."


class FakeBedrock:
    def converse(self, **kwargs):
        return {"output": {"message": {"content": [{"text": '{"verdict": "likely_meets", "reason": "Fine."}'}]}},
                "usage": {"inputTokens": 120, "outputTokens": 30}}


def value(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "arn:aws:bedrock:us-east-1:111111111111:application-inference-profile/test")
    app.dependency_overrides[bedrock_dependency] = lambda: FakeBedrock()
    yield
    app.dependency_overrides.clear()


def test_metrics_endpoint_serves_prometheus_text(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "ctm_gateway_requests_total" in response.text


def test_assess_moves_verdict_token_and_masking_counters(client, fake):
    before = {
        "verdict": value("ctm_gateway_verdicts_total", verdict="likely_meets"),
        "tokens_in": value("ctm_gateway_tokens_total", direction="input"),
        "masked_mrn": value("ctm_gateway_identifiers_masked_total", label="MRN"),
        "ok": value("ctm_gateway_requests_total", endpoint="/v1/assess", status="200"),
    }
    assert client.post("/v1/assess", json={"note": NOTE, "criterion": "No uncontrolled hypertension"}).status_code == 200
    assert value("ctm_gateway_verdicts_total", verdict="likely_meets") == before["verdict"] + 1
    assert value("ctm_gateway_tokens_total", direction="input") == before["tokens_in"] + 120
    assert value("ctm_gateway_identifiers_masked_total", label="MRN") == before["masked_mrn"] + 1
    assert value("ctm_gateway_requests_total", endpoint="/v1/assess", status="200") == before["ok"] + 1


def test_refusals_are_counted_by_label(client, fake):
    before = value("ctm_gateway_refusals_total", label="PHONE")
    response = client.post("/v1/assess", json={"note": "BP fine.", "criterion": "Call (617) 555-0147"})
    assert response.status_code == 422
    assert value("ctm_gateway_refusals_total", label="PHONE") == before + 1


def test_unknown_paths_share_one_label(client):
    client.get("/no-such-page-1")
    client.get("/no-such-page-2")
    text = client.get("/metrics").text
    assert 'endpoint="other"' in text
    assert "no-such-page" not in text


def test_metrics_never_contain_request_text(client, fake):
    client.post("/v1/assess", json={"note": NOTE, "criterion": "No uncontrolled hypertension"})
    text = client.get("/metrics").text
    for value_text in ["John", "Smith", "4821937", "555-0147", "hypertension"]:
        assert value_text not in text, value_text


def test_alerted_series_exist_at_zero_on_start_up():
    # A fresh process: in this one, other tests have already counted requests.
    script = (
        "from prometheus_client import REGISTRY\n"
        "from app import metrics\n"
        "from app.safety import RESIDUAL_PATTERNS\n"
        "checks = [('ctm_gateway_requests_total', {'endpoint': '/v1/assess', 'status': s}) for s in metrics.ASSESS_STATUSES]\n"
        "checks += [('ctm_gateway_request_seconds_count', {'endpoint': '/v1/assess'})]\n"
        "checks += [('ctm_gateway_refusals_total', {'label': l}) for l in RESIDUAL_PATTERNS]\n"
        "checks += [('ctm_gateway_verdicts_total', {'verdict': v}) for v in metrics.VERDICT_VALUES]\n"
        "checks += [('ctm_gateway_tokens_total', {'direction': d}) for d in metrics.TOKEN_DIRECTIONS]\n"
        "for name, labels in checks:\n"
        "    print(name, REGISTRY.get_sample_value(name, labels))\n"
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True).stdout
    lines = out.strip().splitlines()
    assert len(lines) == 4 + 1 + 4 + 3 + 2
    for line in lines:
        assert line.endswith(" 0.0"), line
