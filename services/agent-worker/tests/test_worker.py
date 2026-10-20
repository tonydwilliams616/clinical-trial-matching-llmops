import datetime
import json

from app.worker import parse_job, poll_once
from tests.sample import FakeGateway, dataset

CFG = {"queue_url": "q", "data_bucket": "data", "reference_date": datetime.date(2026, 10, 1),
       "max_candidates": 20, "max_criteria": 5}


class FakeSQS:
    def __init__(self, bodies):
        self.messages = [{"MessageId": str(i), "ReceiptHandle": f"r{i}", "Body": b} for i, b in enumerate(bodies)]
        self.deleted = []

    def receive_message(self, **_):
        return {"Messages": [self.messages.pop(0)]} if self.messages else {}

    def delete_message(self, ReceiptHandle, **_):
        self.deleted.append(ReceiptHandle)


class FakeS3:
    def __init__(self, fail=False):
        self.objects, self.fail = {}, fail

    def put_object(self, Bucket, Key, Body, **_):
        if self.fail:
            raise RuntimeError("AccessDenied")
        self.objects[(Bucket, Key)] = json.loads(Body)


def poll(sqs, s3, gateway=None):
    return poll_once(sqs=sqs, data=dataset(), gateway=gateway or FakeGateway(), s3=s3, cfg=CFG)


def test_result_written_then_message_deleted():
    sqs, s3 = FakeSQS(['{"job_id": "demo-001", "nct_id": "NCT00000001"}']), FakeS3()
    assert poll(sqs, s3) == 1
    assert ("data", "results/v1/demo-001.json") in s3.objects
    assert sqs.deleted == ["r0"]


def test_failed_write_keeps_the_message_for_retry():
    sqs, s3 = FakeSQS(['{"job_id": "demo-001", "nct_id": "NCT00000001"}']), FakeS3(fail=True)
    assert poll(sqs, s3) == 0
    assert sqs.deleted == []


def test_bad_messages_are_not_deleted():
    for body in ["not json", '{"job_id": "../etc", "nct_id": "NCT00000001"}', '{"job_id": "a", "nct_id": "X"}',
                 '{"job_id": "a", "nct_id": "NCT99999999"}']:
        sqs, s3 = FakeSQS([body]), FakeS3()
        assert poll(sqs, s3) == 0 and sqs.deleted == [], body


def test_empty_queue_does_nothing():
    sqs, s3 = FakeSQS([]), FakeS3()
    assert poll(sqs, s3) == 0 and s3.objects == {}


def test_parse_job_keeps_only_known_fields():
    assert parse_job('{"job_id": "a-1", "nct_id": "NCT12345678", "extra": "x"}') == {"job_id": "a-1", "nct_id": "NCT12345678"}
