"""
Gateway traces: the right spans, linked to the caller's trace - and no text.

Spans are captured in memory (nothing is exported in tests). The leak checks
serialise every span to JSON and search it for identifier values, note text
and criterion text, on the success, refusal and model-failure paths.
All values are fake: 555-01xx phones, example.com email.
"""

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.assess import bedrock_dependency
from app.main import app

NOTE = (
    "Patient: John Smith    MRN 4821937\n"
    "Patient contact: (617) 555-0147, email john.s42@example.com.\n"
    "History: hypertension, well controlled on lisinopril. BP 128/82 today."
)
CRITERION = "No history of uncontrolled hypertension"
# Identifier values, plus words that appear only in the note or the criterion
MUST_NOT_APPEAR = ["John", "Smith", "4821937", "555-0147", "john.s42@example.com",
                   "lisinopril", "hypertension", "128/82", "uncontrolled"]

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
CALLER_SPAN_ID = "00f067aa0ba902b7"


class FakeBedrock:
    def __init__(self, error=None):
        self.error = error

    def converse(self, **kwargs):
        if self.error:
            raise self.error
        return {"output": {"message": {"content": [{"text": '{"verdict": "likely_meets", "reason": "Controlled."}'}]}},
                "usage": {"inputTokens": 120, "outputTokens": 30}}


@pytest.fixture(scope="module")
def spans_exporter():
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def spans(spans_exporter):
    spans_exporter.clear()
    yield spans_exporter
    app.dependency_overrides.clear()


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "arn:aws:bedrock:us-east-1:111111111111:application-inference-profile/test")

    def use(fake):
        app.dependency_overrides[bedrock_dependency] = lambda: fake
    return use


def by_name(exporter):
    return {span.name: span for span in exporter.get_finished_spans()}


def assert_no_text(exporter):
    dumped = "".join(span.to_json() for span in exporter.get_finished_spans())
    assert dumped, "no spans were recorded"
    for value in MUST_NOT_APPEAR:
        assert value not in dumped, value


def test_assess_trace_has_one_span_per_step(client, spans, model):
    model(FakeBedrock())
    assert client.post("/v1/assess", json={"note": NOTE, "criterion": CRITERION}).status_code == 200

    named = by_name(spans)
    server = named["POST /v1/assess"]
    for step in ("mask", "leftover_check", "bedrock.converse"):
        assert named[step].context.trace_id == server.context.trace_id, step
        assert named[step].parent.span_id == server.context.span_id, step

    assert named["mask"].attributes["ctm.identifiers_masked"] >= 3
    assert named["leftover_check"].attributes["ctm.refused"] is False
    assert named["bedrock.converse"].attributes["gen_ai.usage.input_tokens"] == 120
    assert named["bedrock.converse"].attributes["gen_ai.usage.output_tokens"] == 30
    assert server.attributes["ctm.verdict"] == "likely_meets"
    assert_no_text(spans)


def test_caller_trace_is_continued(client, spans, model):
    # The worker sends a W3C traceparent header; the gateway joins its trace
    model(FakeBedrock())
    client.post("/v1/assess", json={"note": NOTE, "criterion": CRITERION},
                headers={"traceparent": f"00-{TRACE_ID}-{CALLER_SPAN_ID}-01"})
    server = by_name(spans)["POST /v1/assess"]
    assert format(server.context.trace_id, "032x") == TRACE_ID
    assert format(server.parent.span_id, "016x") == CALLER_SPAN_ID


def test_refusal_is_traced_without_values(client, spans, model):
    fake = FakeBedrock()
    model(fake)
    response = client.post("/v1/assess", json={"note": NOTE, "criterion": "Reachable at (617) 555-0147"})
    assert response.status_code == 422

    named = by_name(spans)
    assert named["leftover_check"].attributes["ctm.refused"] is True
    assert list(named["leftover_check"].attributes["ctm.leftover_labels"]) == ["PHONE"]
    assert "bedrock.converse" not in named  # nothing was sent
    assert_no_text(spans)


def test_model_failure_is_traced_without_details(client, spans, model):
    model(FakeBedrock(error=RuntimeError("AccessDenied for arn:aws:iam::secret")))
    assert client.post("/v1/assess", json={"note": NOTE, "criterion": CRITERION}).status_code == 502

    span = by_name(spans)["bedrock.converse"]
    assert span.status.status_code == trace.StatusCode.ERROR
    assert span.status.description == "model unavailable"
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.events == ()  # no exception event with its message
    dumped = span.to_json()
    assert "secret" not in dumped and "AccessDenied" not in dumped
    assert_no_text(spans)


def test_mask_endpoint_is_traced_without_text(client, spans):
    assert client.post("/v1/mask", json={"text": NOTE}).status_code == 200
    named = by_name(spans)
    assert "POST /v1/mask" in named and "mask" in named
    assert_no_text(spans)


def test_probes_and_scrapes_are_not_traced(client, spans):
    for path in ("/healthz", "/readyz", "/metrics"):
        client.get(path)
    assert spans.get_finished_spans() == ()
