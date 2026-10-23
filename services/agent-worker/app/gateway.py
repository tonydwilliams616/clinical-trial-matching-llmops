"""
Client for the PII gateway's /v1/assess - the worker's only route to a model.

Standard library only. The raw note travels inside the cluster to the
gateway (allowed by its NetworkPolicy); the gateway masks it before anything
reaches Bedrock.

    200 -> the gateway's verdict
    422 -> "refused": the gateway's safety check stopped the note; nothing was
           sent to the model. Recorded for review, not retried.
    5xx / network error -> GatewayError, so the whole job is retried later
"""

import json
import urllib.error
import urllib.request

from opentelemetry import propagate
from opentelemetry.trace import SpanKind, Status, StatusCode

from .tracing import tracer


class GatewayError(Exception):
    pass


class GatewayClient:
    def __init__(self, base_url: str, timeout: float = 60):
        self.url = base_url.rstrip("/") + "/v1/assess"
        self.timeout = timeout

    def assess(self, note: str, criterion: str) -> dict:
        # One client span per question. Its context travels to the gateway in a
        # W3C traceparent header, so the gateway's spans join this job's trace.
        # Status code and verdict only: never the note, criterion or reason.
        with tracer.start_as_current_span(
            "gateway.assess", kind=SpanKind.CLIENT,
            record_exception=False, set_status_on_exception=False,
            attributes={"http.request.method": "POST", "url.full": self.url},
        ) as span:
            try:
                result = self._post(note, criterion, span)
            except GatewayError as exc:
                span.set_attribute("error.type", str(exc).split(":")[0])  # e.g. "HTTP 502", "URLError"
                span.set_status(Status(StatusCode.ERROR, "gateway error"))
                raise
            span.set_attribute("ctm.verdict", result["verdict"])
            return result

    def _post(self, note: str, criterion: str, span) -> dict:
        body = json.dumps({"note": note, "criterion": criterion}).encode()
        headers = {"content-type": "application/json"}
        propagate.inject(headers)  # adds traceparent for the current span
        request = urllib.request.Request(self.url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                span.set_attribute("http.response.status_code", response.status)
                reply = json.load(response)
            return {"verdict": reply["verdict"], "reason": reply["reason"]}
        except urllib.error.HTTPError as exc:
            span.set_attribute("http.response.status_code", exc.code)
            if exc.code == 422:
                return {"verdict": "refused", "reason": "Gateway safety check stopped this note; nothing was sent to the model."}
            # The gateway's own short error text ("model unavailable"), never request content
            raise GatewayError(f"HTTP {exc.code}: {_detail(exc)}") from None
        except urllib.error.URLError as exc:
            raise GatewayError(f"URLError: {type(exc.reason).__name__}: {exc.reason}"[:200]) from None
        except (TimeoutError, KeyError, ValueError) as exc:
            raise GatewayError(type(exc).__name__) from None


def _detail(exc: urllib.error.HTTPError) -> str:
    """The gateway's `detail` string if it sent JSON, else nothing."""
    try:
        detail = json.loads(exc.read() or b"{}").get("detail")
    except ValueError:
        return "no detail"
    return detail[:120] if isinstance(detail, str) else "no detail"
