"""
Prometheus metrics for the agent worker - numbers only, never text.

The worker serves no web traffic, so prometheus-client runs a tiny HTTP server
on its own port (METRICS_PORT, default 9100) just for Prometheus to scrape.
Note: KEDA scales workers to zero when the queue is empty, so these series
exist only while workers run; queue depth itself comes from SQS/KEDA.
Labelled counters are created at zero on start-up (see below) so that alerts
using increase() see the very first job or failure.

    ctm_worker_jobs_total{outcome}              jobs finished: done / failed
    ctm_worker_job_seconds                      how long a job takes
    ctm_worker_questions_total{verdict}         gateway answers per verdict (incl. refused)
    ctm_worker_candidates_total{status}         shortlisted / not_shortlisted / insufficient_evidence
    ctm_worker_gateway_errors_total             jobs failed because the gateway failed
    ctm_worker_dataset_load_seconds             start-up time to load the datasets
"""

from prometheus_client import Counter, Gauge, Histogram

JOBS = Counter("ctm_worker_jobs_total", "Jobs finished", ["outcome"])
JOB_SECONDS = Histogram(
    "ctm_worker_job_seconds", "Job duration",
    buckets=(5, 10, 20, 30, 60, 90, 120, 180, 240, 300),
)
QUESTIONS = Counter("ctm_worker_questions_total", "Gateway answers by verdict", ["verdict"])
CANDIDATES = Counter("ctm_worker_candidates_total", "Assessed candidates by status", ["status"])
GATEWAY_ERRORS = Counter("ctm_worker_gateway_errors_total", "Jobs failed by a gateway error")
DATASET_LOAD_SECONDS = Gauge("ctm_worker_dataset_load_seconds", "Time to load the datasets at start-up")

# Every label value a counter can take, created at zero when the worker starts.
# A labelled counter otherwise appears only at its first increment - already at
# 1 or more - and Prometheus, never having seen it at 0, computes increase() = 0.
# On EKS (25 Oct) a worker failed two jobs between scrapes and CtmJobsFailing
# stayed silent for exactly that reason.
OUTCOMES = ("done", "failed")
VERDICTS = ("likely_meets", "likely_fails", "unclear", "refused")
STATUSES = ("shortlisted", "not_shortlisted", "insufficient_evidence")

for _outcome in OUTCOMES:
    JOBS.labels(outcome=_outcome)
for _verdict in VERDICTS:
    QUESTIONS.labels(verdict=_verdict)
for _status in STATUSES:
    CANDIDATES.labels(status=_status)


def record_result(result: dict, seconds: float) -> None:
    JOBS.labels(outcome="done").inc()
    JOB_SECONDS.observe(seconds)
    for candidate in result["candidates"]:
        CANDIDATES.labels(status=candidate["status"]).inc()
        for answer in candidate["free_text_criteria"]:
            QUESTIONS.labels(verdict=answer["verdict"]).inc()
