"""
pii-gateway HTTP API.

    GET  /healthz   liveness  - the process is up
    GET  /readyz    readiness - the language model is loaded, safe to send traffic
    POST /v1/mask   {"text": "..."} -> masked text + what was found (no values)

Later PRs add the Bedrock call behind this, and metrics/tracing.

Rule: request text is never logged. Logs carry sizes, counts and timings only.
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .masker import Masker

MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "20000"))
GIT_SHA = os.getenv("GIT_SHA", "dev")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
log = logging.getLogger("pii_gateway")

engine: dict[str, Masker] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    started = time.perf_counter()
    engine["masker"] = Masker()  # loads the spaCy model: a few seconds
    log.info(json.dumps({"event": "ready", "version": GIT_SHA,
                         "load_ms": round((time.perf_counter() - started) * 1000)}))
    yield
    engine.clear()


app = FastAPI(title="pii-gateway", version=GIT_SHA, lifespan=lifespan)


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
    result = engine["masker"].mask(request.text)
    log.info(json.dumps({
        "event": "mask",
        "chars": len(request.text),
        "findings": len(result["findings"]),
        "ms": round((time.perf_counter() - started) * 1000, 1),
    }))
    return result
