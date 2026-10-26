"""
Prometheus metrics for the gateway - numbers only, never text.

Exposed at GET /metrics for Prometheus to scrape. Every label has a small,
fixed set of values (endpoints, status codes, identifier labels, verdicts),
so the number of time series stays bounded whatever the traffic.

    ctm_gateway_requests_total{endpoint,status}      every HTTP request
    ctm_gateway_request_seconds{endpoint}            how long requests take
    ctm_gateway_identifiers_masked_total{label}      what masking removed
    ctm_gateway_refusals_total{label}                safety-net refusals, by leftover type
    ctm_gateway_bedrock_seconds                      model call latency
    ctm_gateway_bedrock_errors_total                 failed model calls
    ctm_gateway_tokens_total{direction}              Bedrock tokens in/out (cost)
    ctm_gateway_verdicts_total{verdict}              likely_meets / likely_fails / unclear
"""

from prometheus_client import Counter, Histogram

KNOWN_ENDPOINTS = {"/v1/assess", "/v1/mask", "/healthz", "/readyz", "/metrics"}

REQUESTS = Counter("ctm_gateway_requests_total", "HTTP requests", ["endpoint", "status"])
REQUEST_SECONDS = Histogram(
    "ctm_gateway_request_seconds", "HTTP request duration", ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
IDENTIFIERS_MASKED = Counter("ctm_gateway_identifiers_masked_total", "Identifiers masked", ["label"])
REFUSALS = Counter("ctm_gateway_refusals_total", "Requests refused by the leftover check", ["label"])
BEDROCK_SECONDS = Histogram(
    "ctm_gateway_bedrock_seconds", "Bedrock call duration",
    buckets=(0.25, 0.5, 1, 2, 3, 5, 10, 20, 30),
)
BEDROCK_ERRORS = Counter("ctm_gateway_bedrock_errors_total", "Failed Bedrock calls")
TOKENS = Counter("ctm_gateway_tokens_total", "Bedrock tokens", ["direction"])
VERDICTS = Counter("ctm_gateway_verdicts_total", "Assess verdicts", ["verdict"])


# Label values the alerts and SLO rules depend on, created at zero when the
# gateway starts. A labelled series otherwise appears only at its first
# increment, already above 0, and Prometheus's increase() can't see that first
# rise: on EKS (25 Oct) the worker's equivalent left an alert silent through a
# real outage. Refusal labels come from the leftover check itself.
ASSESS_STATUSES = ("200", "422", "502", "503")
VERDICT_VALUES = ("likely_meets", "likely_fails", "unclear")
TOKEN_DIRECTIONS = ("input", "output")


def _create_at_zero() -> None:
    from .safety import RESIDUAL_PATTERNS

    for status in ASSESS_STATUSES:
        REQUESTS.labels(endpoint="/v1/assess", status=status)
    REQUEST_SECONDS.labels(endpoint="/v1/assess")
    for label in RESIDUAL_PATTERNS:
        REFUSALS.labels(label=label)
    for verdict in VERDICT_VALUES:
        VERDICTS.labels(verdict=verdict)
    for direction in TOKEN_DIRECTIONS:
        TOKENS.labels(direction=direction)


_create_at_zero()


def endpoint_label(path: str) -> str:
    """Known paths as themselves; anything else as "other" (keeps series bounded)."""
    return path if path in KNOWN_ENDPOINTS else "other"


def record_masked(counts: dict[str, int]) -> None:
    for label, n in counts.items():
        IDENTIFIERS_MASKED.labels(label=label).inc(n)
