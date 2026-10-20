"""
pii-gateway HTTP API.

    GET  /healthz   liveness  - the process is up
    GET  /readyz    readiness - the language model is loaded, safe to send traffic
    POST /v1/mask   {"text": "..."} -> masked text + what was found (no values)
    POST /v1/assess {"note": "...", "criterion": "..."} -> mask the note, then ask
                    the model whether the patient appears to meet the criterion

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

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .assess import ModelUnavailable, bedrock_dependency, call_model, model_id, parse_reply
from .masker import Masker
from .safety import residual_identifiers

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
    masked = engine["masker"].mask(request.note)
    leftovers = residual_identifiers(masked["masked_text"] + "\n" + request.criterion)
    if leftovers:
        log.warning(json.dumps({"event": "assess_refused", "leftover": leftovers}))
        raise HTTPException(status_code=422, detail="masking incomplete; nothing was sent to the model")

    # 3. Ask the model; 4. an unreadable reply becomes "unclear", never a guess.
    try:
        reply, usage = call_model(client, profile, request.criterion, masked["masked_text"])
    except ModelUnavailable as exc:
        log.error(json.dumps({"event": "assess_model_error", "error": str(exc)}))
        raise HTTPException(status_code=502, detail="model unavailable") from None
    verdict, reason = parse_reply(reply)

    log.info(json.dumps({
        "event": "assess",
        "verdict": verdict,
        "masked": len(masked["findings"]),
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
        "ms": round((time.perf_counter() - started) * 1000, 1),
    }))
    return {"verdict": verdict, "reason": reason, "counts": masked["counts"]}
