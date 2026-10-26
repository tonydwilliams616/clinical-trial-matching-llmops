"""Worker metrics: jobs, answers and candidates are counted; no text leaks."""

import subprocess
import sys

from prometheus_client import REGISTRY, generate_latest

from tests.sample import FakeGateway
from tests.test_worker import FailingGateway, FakeS3, FakeSQS, poll

JOB = '{"job_id": "demo-001", "nct_id": "NCT00000001"}'


def value(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_finished_job_is_counted_with_its_answers_and_candidates():
    before_done = value("ctm_worker_jobs_total", outcome="done")
    before_meets = value("ctm_worker_questions_total", verdict="likely_meets")
    before_short = value("ctm_worker_candidates_total", status="shortlisted")
    assert poll(FakeSQS([JOB]), FakeS3(), gateway=FakeGateway()) == 1
    assert value("ctm_worker_jobs_total", outcome="done") == before_done + 1
    assert value("ctm_worker_questions_total", verdict="likely_meets") > before_meets
    assert value("ctm_worker_candidates_total", status="shortlisted") == before_short + 2
    assert value("ctm_worker_job_seconds_count") >= 1


def test_gateway_failure_counts_as_failed_job_and_gateway_error():
    before_failed = value("ctm_worker_jobs_total", outcome="failed")
    before_gw = value("ctm_worker_gateway_errors_total")
    assert poll(FakeSQS([JOB]), FakeS3(), gateway=FailingGateway()) == 0
    assert value("ctm_worker_jobs_total", outcome="failed") == before_failed + 1
    assert value("ctm_worker_gateway_errors_total") == before_gw + 1


def test_metrics_never_contain_note_text_or_ids():
    poll(FakeSQS([JOB]), FakeS3(), gateway=FakeGateway())
    text = generate_latest().decode()
    for value_text in ["Jane Doe", "p-ok-1", "NCT00000001", "demo-001"]:
        assert value_text not in text, value_text


def test_every_label_value_exists_at_zero_on_start_up():
    # Checked in a fresh process: in this one, other tests have already counted.
    # Without this, a worker's first failure appears at 1 and increase() sees 0.
    script = (
        "from prometheus_client import REGISTRY\n"
        "from app import metrics\n"
        "pairs = ([('ctm_worker_jobs_total', 'outcome', v) for v in metrics.OUTCOMES]"
        " + [('ctm_worker_questions_total', 'verdict', v) for v in metrics.VERDICTS]"
        " + [('ctm_worker_candidates_total', 'status', v) for v in metrics.STATUSES])\n"
        "for name, label, v in pairs:\n"
        "    print(name, v, REGISTRY.get_sample_value(name, {label: v}))\n"
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True).stdout
    lines = out.strip().splitlines()
    assert len(lines) == 9
    for line in lines:
        assert line.endswith(" 0.0"), line
