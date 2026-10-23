"""
OpenTelemetry tracing for the gateway - timings, counts and fixed labels only.

Every request to /v1/mask and /v1/assess becomes a trace with child spans:

    POST /v1/assess                 (server span, from the FastAPI instrumentation)
      mask                          ctm.identifiers_masked
      leftover_check                ctm.leftover_labels, ctm.refused
      bedrock.converse              gen_ai.* token counts, error.type on failure

A caller that sends a W3C `traceparent` header (the agent worker) gets these
spans attached to its own trace, so one match job reads end to end.

Rule, the same as for logs and metrics: no span name, attribute or event may
contain note text, criterion text or an identifier value. Exceptions are never
recorded on spans (their messages could carry text); failures set a fixed
status description instead. tests/test_tracing.py checks this.

Spans are exported only when OTEL_EXPORTER_OTLP_ENDPOINT is set (the EKS
overlay points it at Tempo). Without it - local runs, kind, tests - spans are
created but go nowhere.
"""

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "pii-gateway"

# Probes and scrapes every few seconds would bury the traces that matter
EXCLUDED_URLS = "/healthz,/readyz,/metrics"

# ProxyTracer: safe to create before configure() runs
tracer = trace.get_tracer("pii_gateway")


def configure(app, version: str) -> TracerProvider:
    """Install the tracer provider and instrument the FastAPI app (once, at import)."""
    provider = TracerProvider(resource=Resource.create({
        "service.name": SERVICE_NAME,
        "service.version": version,
    }))
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # OTLP over HTTP; the exporter adds /v1/traces to the endpoint
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=EXCLUDED_URLS,
        # Skip the per-message ASGI send/receive spans: noise, no insight
        exclude_spans=["receive", "send"],
    )
    return provider
