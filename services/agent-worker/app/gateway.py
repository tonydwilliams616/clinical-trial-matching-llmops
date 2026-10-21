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


class GatewayError(Exception):
    pass


class GatewayClient:
    def __init__(self, base_url: str, timeout: float = 60):
        self.url = base_url.rstrip("/") + "/v1/assess"
        self.timeout = timeout

    def assess(self, note: str, criterion: str) -> dict:
        body = json.dumps({"note": note, "criterion": criterion}).encode()
        request = urllib.request.Request(self.url, data=body, method="POST",
                                         headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                reply = json.load(response)
            return {"verdict": reply["verdict"], "reason": reply["reason"]}
        except urllib.error.HTTPError as exc:
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
