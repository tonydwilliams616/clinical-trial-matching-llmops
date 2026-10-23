"""
pii-gateway HTTP API.

    GET  /healthz   liveness  - the process is up
    GET  /readyz    readiness - the language model is loaded, safe to send traffic
    POST /v1/mask   {"text": "..."} -> masked text + what was found (no values)
    POST /v1/assess {"note": "...", "criterion": "..."} -> mask the note, then ask
                    the model whether the patient appears to meet the criterion
    GET  /metrics   Prometheus metrics (numbers only - see metrics.py)

Traces (tracing.py) follow each request through masking, the leftover check
and the model call - timings and counts only, like the logs and metrics.

Only /v1/assess talks to the model, and only after masking plus an independent
leftover-identifier check (safety.py). If either fails, nothing is sent.

Rule: request text is never logged. Logs carry sizes, counts and timings only.
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import metrics, tracing
from .assess import ModelUnavailable, bedrock_dependency, call_model, model_id, parse_reply
from .masker import Masker
from .safety import residual_identifiers, residual_shapes

MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "20000"))
GIT_SHA = os.getenv("GIT_SHA", "dev")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
log = logging.getLogger("pii_gateway")

engine: dict[str, Masker] = {}


# Start-up self-test: one line with one of each fixed-shape identifier. If any
# survives masking, the gateway refuses to become ready - a broken recognizer
# shows up as a pod that never turns Ready, not as hours of silent refusals.
SELF_TEST = "Contact (617) 555-0147, email jane.d42@example.com, SSN 999-52-8841, MRN 4821937."


def self_test(masker: Masker) -> None:
    masked = masker.mask(SELF_TEST)["masked_text"]
    leftovers = residual_identifiers(masked)
    if leftovers:
        raise RuntimeError(f"masking self-test failed: {leftovers} not masked")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    started = time.perf_counter()
    masker = Masker()  # loads the spaCy model: a few seconds
    self_test(masker)  # raises: the process exits and Kubernetes shows the restart
    engine["masker"] = masker
    log.info(json.dumps({"event": "ready", "version": GIT_SHA,
                         "load_ms": round((time.perf_counter() - started) * 1000)}))
    yield
    engine.clear()
    # Send any spans still buffered before the pod stops (flush, not shutdown:
    # the provider is process-wide and outlives one app start/stop in tests)
    tracer_provider.force_flush()


app = FastAPI(title="pii-gateway", version=GIT_SHA, lifespan=lifespan)
tracer_provider = tracing.configure(app, GIT_SHA)


def masked_in_span(text: str) -> dict:
    """Mask text inside a "mask" span that records how many identifiers were found."""
    with tracing.tracer.start_as_current_span("mask") as span:
        result = engine["masker"].mask(text)
        span.set_attribute("ctm.identifiers_masked", len(result["findings"]))
        return result


@app.middleware("http")
async def count_requests(request: Request, call_next):
    started = time.perf_counter()
    endpoint = metrics.endpoint_label(request.url.path)
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        metrics.REQUESTS.labels(endpoint=endpoint, status=str(status)).inc()
        metrics.REQUEST_SECONDS.labels(endpoint=endpoint).observe(time.perf_counter() - started)


@app.get("/metrics")
def prometheus_metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class MaskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class Finding(BaseModel):
    label: str
    start: int
    end: int
    score: float


class MaskResponse(BaseModel):
    masked_text: str
    findings: list[Finding]
    counts: dict[str, int]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict:
    if "masker" not in engine:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {"status": "ready", "version": GIT_SHA}


# Plain `def` (not async): masking is CPU work, so FastAPI runs it in a
# thread pool instead of blocking the event loop.
@app.post("/v1/mask", response_model=MaskResponse)
def mask(request: MaskRequest) -> dict:
    started = time.perf_counter()
    result = masked_in_span(request.text)
    metrics.record_masked(result["counts"])
    log.info(json.dumps({
        "event": "mask",
        "chars": len(request.text),
        "findings": len(result["findings"]),
        "ms": round((time.perf_counter() - started) * 1000, 1),
    }))
    return result


class AssessRequest(BaseModel):
    note: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    criterion: str = Field(min_length=1, max_length=1000)


class AssessResponse(BaseModel):
    verdict: Literal["likely_meets", "likely_fails", "unclear"]
    reason: str
    counts: dict[str, int]  # identifiers masked before the model saw the note


@app.post("/v1/assess", response_model=AssessResponse)
def assess(request: AssessRequest, client=Depends(bedrock_dependency)) -> dict:
    started = time.perf_counter()
    profile = model_id()
    if profile is None or client is None:
        raise HTTPException(status_code=503, detail="model not configured")

    # 1. Mask, then 2. check independently that nothing obvious slipped through.
    # Either failing means nothing is sent - there is no "send it anyway" path.
    masked = masked_in_span(request.note)
    metrics.record_masked(masked["counts"])
    checked = masked["masked_text"] + "\n" + request.criterion
    with tracing.tracer.start_as_current_span("leftover_check") as span:
        leftovers = residual_identifiers(checked)
        span.set_attribute("ctm.leftover_labels", leftovers)  # labels like "EMAIL", never values
        span.set_attribute("ctm.refused", bool(leftovers))
    if leftovers:
        for label in leftovers:
            metrics.REFUSALS.labels(label=label).inc()
        # Shapes, never values: letters and digits generalised, placeholders kept
        log.warning(json.dumps({"event": "assess_refused", "leftover": leftovers,
                                "shapes": residual_shapes(checked)}))
        raise HTTPException(status_code=422, detail="masking incomplete; nothing was sent to the model")

    # 3. Ask the model; 4. an unreadable reply becomes "unclear", never a guess.
    model_started = time.perf_counter()
    # Exceptions are never recorded on the span: a fixed status and the error
    # class name (e.g. "ReadTimeoutError") say enough without risking text.
    with tracing.tracer.start_as_current_span(
        "bedrock.converse", kind=SpanKind.CLIENT,
        record_exception=False, set_status_on_exception=False,
    ) as span:
        span.set_attribute("gen_ai.system", "aws.bedrock")
        span.set_attribute("gen_ai.operation.name", "chat")
        try:
            reply, usage = call_model(client, profile, request.criterion, masked["masked_text"])
        except ModelUnavailable as exc:
            span.set_attribute("error.type", str(exc))
            span.set_status(Status(StatusCode.ERROR, "model unavailable"))
            metrics.BEDROCK_ERRORS.inc()
            log.error(json.dumps({"event": "assess_model_error", "error": str(exc)}))
            raise HTTPException(status_code=502, detail="model unavailable") from None
        span.set_attribute("gen_ai.usage.input_tokens", usage.get("inputTokens") or 0)
        span.set_attribute("gen_ai.usage.output_tokens", usage.get("outputTokens") or 0)
    metrics.BEDROCK_SECONDS.observe(time.perf_counter() - model_started)
    metrics.TOKENS.labels(direction="input").inc(usage.get("inputTokens") or 0)
    metrics.TOKENS.labels(direction="output").inc(usage.get("outputTokens") or 0)
    verdict, reason = parse_reply(reply)
    metrics.VERDICTS.labels(verdict=verdict).inc()
    # On the request's server span: one of three fixed values
    trace.get_current_span().set_attribute("ctm.verdict", verdict)

    log.info(json.dumps({
        "event": "assess",
        "verdict": verdict,
        "masked": len(masked["findings"]),
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
        "ms": round((time.perf_counter() - started) * 1000, 1),
    }))
    return {"verdict": verdict, "reason": reason, "counts": masked["counts"]}
