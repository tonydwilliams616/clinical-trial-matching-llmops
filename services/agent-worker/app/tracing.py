"""
OpenTelemetry tracing for the worker - IDs, counts and timings only.

One trace per match job:

    match_job                 ctm.job_id, ctm.nct_id, result counts
      gateway.assess  (xN)    http status, ctm.verdict
        POST /v1/assess       the gateway's own spans (mask, leftover check,
          ...                 Bedrock) join here via the traceparent header
      s3.put_result

Rule, the same as for logs and metrics: no span carries note text, criterion
text, patient IDs or identifier values. Exceptions are never recorded on spans;
failures set a fixed status and the error class name instead.
tests/test_tracing.py checks this.

Spans are exported only when OTEL_EXPORTER_OTLP_ENDPOINT is set (the EKS
overlay points it at Tempo). Without it - local runs, tests - spans go nowhere.
"""

import os

from opentelemetry import trace

SERVICE_NAME = "agent-worker"

# ProxyTracer: safe to use before configure() runs (spans are no-ops until then)
tracer = trace.get_tracer("agent_worker")


def configure(version: str):
    """Install the tracer provider. Called once from main(); returns it for shutdown."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({
        "service.name": SERVICE_NAME,
        "service.version": version,
    }))
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # OTLP over HTTP; the exporter adds /v1/traces to the endpoint
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider
