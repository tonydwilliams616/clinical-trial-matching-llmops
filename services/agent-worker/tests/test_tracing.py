"""
Worker traces: one trace per job, the trace passed on to the gateway - and no
note text, criterion text or patient IDs in any span.

Spans are captured in memory (nothing is exported in tests).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.gateway import GatewayClient, GatewayError
from tests.sample import FakeGateway
from tests.test_worker import FakeS3, FakeSQS, poll

JOB = '{"job_id": "demo-001", "nct_id": "NCT00000001"}'
# Note words, criterion words and patient IDs from tests/sample.py
MUST_NOT_APPEAR = ["Jane Doe", "John Roe", "Metformin", "128/82", "hypertension",
                   "insulin", "pregnant", "p-ok-1", "p-ok-2"]


@pytest.fixture(scope="module")
def exporter():
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):  # main() is not run in tests
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    return memory


@pytest.fixture
def spans(exporter):
    exporter.clear()
    return exporter


def by_name(exporter):
    return {span.name: span for span in exporter.get_finished_spans()}


def assert_no_text(exporter):
    dumped = "".join(span.to_json() for span in exporter.get_finished_spans())
    assert dumped, "no spans were recorded"
    for value in MUST_NOT_APPEAR:
        assert value not in dumped, value


def test_job_is_one_trace_with_ids_and_counts(spans):
    assert poll(FakeSQS([JOB]), FakeS3()) == 1
    named = by_name(spans)
    job = named["match_job"]
    assert job.kind == trace.SpanKind.CONSUMER
    assert job.attributes["ctm.job_id"] == "demo-001"
    assert job.attributes["ctm.nct_id"] == "NCT00000001"
    assert job.attributes["ctm.patients_screened"] == (
        job.attributes["ctm.failed_hard_criteria"] + job.attributes["ctm.passed_hard_criteria"])
    assert job.attributes["ctm.model_questions"] >= 1
    put = named["s3.put_result"]
    assert put.parent.span_id == job.context.span_id
    assert_no_text(spans)


def test_failed_job_is_marked_without_details(spans):
    assert poll(FakeSQS([JOB]), FakeS3(fail=True)) == 0
    job = by_name(spans)["match_job"]
    assert job.status.status_code == trace.StatusCode.ERROR
    assert job.status.description == "job failed"
    assert job.attributes["error.type"] == "RuntimeError"
    assert job.events == ()  # no exception event, so no "AccessDenied" text
    assert "AccessDenied" not in job.to_json()


def test_bad_message_is_marked_failed(spans):
    assert poll(FakeSQS(["not json"]), FakeS3()) == 0
    job = by_name(spans)["match_job"]
    assert job.status.status_code == trace.StatusCode.ERROR
    assert "ctm.job_id" not in job.attributes


def serve(status, body, seen):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.update(self.headers.items())
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, GatewayClient(f"http://127.0.0.1:{server.server_port}", timeout=5)


def test_trace_context_is_sent_to_the_gateway(spans):
    seen = {}
    server, client = serve(200, {"verdict": "likely_meets", "reason": "fine", "counts": {}}, seen)
    with trace.get_tracer("test").start_as_current_span("match_job"):
        client.assess("Seen Jane Doe. BP 128/82.", "History of uncontrolled hypertension")
    server.shutdown()

    call = by_name(spans)["gateway.assess"]
    traceparent = {k.lower(): v for k, v in seen.items()}["traceparent"]
    trace_id, span_id = traceparent.split("-")[1:3]
    assert trace_id == format(call.context.trace_id, "032x")  # same trace as the job
    assert span_id == format(call.context.span_id, "016x")    # gateway's parent is this call
    assert call.attributes["http.response.status_code"] == 200
    assert call.attributes["ctm.verdict"] == "likely_meets"
    assert_no_text(spans)


def test_refusal_and_errors_on_the_gateway_span(spans):
    server, client = serve(422, {"detail": "masking incomplete"}, {})
    assert client.assess("Seen Jane Doe.", "criterion")["verdict"] == "refused"
    server.shutdown()
    assert by_name(spans)["gateway.assess"].attributes["ctm.verdict"] == "refused"

    spans.clear()
    server, client = serve(502, {"detail": "model unavailable"}, {})
    with pytest.raises(GatewayError):
        client.assess("Seen Jane Doe.", "criterion")
    server.shutdown()
    call = by_name(spans)["gateway.assess"]
    assert call.status.status_code == trace.StatusCode.ERROR
    assert call.attributes["error.type"] == "HTTP 502"
    assert call.attributes["http.response.status_code"] == 502
    assert_no_text(spans)


def test_fake_gateway_jobs_still_work_without_a_provider_configured():
    # Sanity: tracing never changes results (FakeGateway records the same calls)
    gateway = FakeGateway()
    assert poll(FakeSQS([JOB]), FakeS3(), gateway=gateway) == 1
    assert gateway.calls
