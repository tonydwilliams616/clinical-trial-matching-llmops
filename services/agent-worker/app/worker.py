"""
agent-worker: take match jobs from SQS, write shortlists to S3.

    {"job_id": "demo-001", "nct_id": "NCT01234567"}   <- message on ctm-match-jobs

For each message:
  1. run the job (matcher.py): hard criteria in code, free text via the gateway
  2. write the result to s3://<data bucket>/results/v1/<job_id>.json
  3. delete the message - only after the result is safely written

If anything fails, the message is NOT deleted: SQS shows it again after the
visibility timeout (5 minutes), and after 3 failed attempts moves it to the
dead-letter queue for inspection. KEDA scales these workers on queue depth,
down to zero when there is nothing to do.

On SIGTERM (scale-down, node drain) the current job finishes before exit.
Logs carry IDs, counts and timings - never note text.
"""

import datetime
import json
import logging
import os
import re
import signal
import time

from .data import Dataset
from .gateway import GatewayClient
from .matcher import run_job

JOB_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
NCT_ID = re.compile(r"^NCT\d{8}$")

log = logging.getLogger("agent_worker")


def settings() -> dict:
    return {
        "queue_url": os.environ["QUEUE_URL"],
        "raw_bucket": os.environ["RAW_BUCKET"],
        "data_bucket": os.environ["DATA_BUCKET"],
        "gateway_url": os.getenv("GATEWAY_URL", "http://pii-gateway.pii-gateway"),
        "reference_date": datetime.date.fromisoformat(os.getenv("REFERENCE_DATE", "2026-10-01")),
        "max_candidates": int(os.getenv("MAX_CANDIDATES", "20")),
        "max_criteria": int(os.getenv("MAX_CRITERIA", "5")),
    }


def parse_job(body: str) -> dict:
    job = json.loads(body)
    if not isinstance(job, dict) or not JOB_ID.match(str(job.get("job_id", ""))) \
            or not NCT_ID.match(str(job.get("nct_id", ""))):
        raise ValueError("invalid job message")
    return {"job_id": job["job_id"], "nct_id": job["nct_id"]}


def handle(message: dict, *, data, gateway, s3, cfg: dict) -> dict:
    """Run one job and store its result. Raises on any failure (message is then retried)."""
    job = parse_job(message["Body"])
    started = time.perf_counter()
    result = run_job(job, data, gateway, reference=cfg["reference_date"],
                     max_candidates=cfg["max_candidates"], max_criteria=cfg["max_criteria"])
    s3.put_object(Bucket=cfg["data_bucket"], Key=f"results/v1/{job['job_id']}.json",
                  Body=json.dumps(result, indent=2).encode(), ContentType="application/json")
    log.info(json.dumps({"event": "job_done", "job_id": job["job_id"], "nct_id": job["nct_id"],
                         **result["counts"], "seconds": round(time.perf_counter() - started, 1)}))
    return result


def poll_once(*, sqs, data, gateway, s3, cfg: dict) -> int:
    """One long-poll for a single message. Returns how many jobs completed (0 or 1)."""
    reply = sqs.receive_message(QueueUrl=cfg["queue_url"], MaxNumberOfMessages=1, WaitTimeSeconds=20)
    done = 0
    for message in reply.get("Messages", []):
        try:
            handle(message, data=data, gateway=gateway, s3=s3, cfg=cfg)
        except Exception as exc:  # leave the message: SQS retries it, then dead-letters it
            log.error(json.dumps({"event": "job_failed", "message_id": message.get("MessageId"),
                                  "error": type(exc).__name__}))
            continue
        sqs.delete_message(QueueUrl=cfg["queue_url"], ReceiptHandle=message["ReceiptHandle"])
        done += 1
    return done


def aws_clients():
    """S3 and SQS clients that fail fast and use regional S3 addresses.

    In us-east-1, boto3 can still default to S3's legacy global hostname
    (s3.amazonaws.com), which resolves to public IPs. The S3 interface endpoint
    only covers s3.us-east-1.amazonaws.com, and the worker's egress
    NetworkPolicy allows HTTPS inside the VPC only - so the global hostname
    hangs. Found in the first EKS session: the worker sat silent loading data.

    Short connect timeouts turn a blocked connection into a quick, logged
    failure (and a visible pod restart) instead of a silent hang. The read
    timeout stays above SQS long polling (20 s).
    """
    import boto3  # imported here so the rest of the module tests without AWS libraries
    from botocore.config import Config

    config = Config(
        connect_timeout=5,
        read_timeout=30,
        retries={"mode": "standard", "max_attempts": 3},
        s3={"us_east_1_regional_endpoint": "regional"},
    )
    return boto3.client("s3", config=config), boto3.client("sqs", config=config)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
    cfg = settings()
    stopping = {"now": False}

    def stop(*_):
        stopping["now"] = True  # finish the current job, then exit
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    s3, sqs = aws_clients()
    started = time.perf_counter()
    data = Dataset.from_s3(s3, cfg["raw_bucket"], cfg["data_bucket"])
    log.info(json.dumps({"event": "ready", "patients_with_notes": len(data.patient_ids_with_notes()),
                         "load_seconds": round(time.perf_counter() - started, 1)}))
    gateway = GatewayClient(cfg["gateway_url"])
    while not stopping["now"]:
        poll_once(sqs=sqs, data=data, gateway=gateway, s3=s3, cfg=cfg)
    log.info(json.dumps({"event": "stopped"}))


if __name__ == "__main__":
    main()
