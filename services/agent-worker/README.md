# agent-worker

Takes match jobs from SQS and writes shortlists to S3. One job = one trial:

```json
{"job_id": "demo-001", "nct_id": "NCT01234567"}
```

| Step | Where | How |
| --- | --- | --- |
| Hard criteria: age, sex, active diagnosis | `app/hard.py` | In code: exact, free, never sent to a model |
| Free-text criteria | `app/criteria.py`, `app/gateway.py` | Split from the trial's eligibility text (exclusions phrased as "Must NOT have: ..."), then sent one at a time to the PII gateway's `/v1/assess`, which masks the note before asking Bedrock |
| Shortlist | `app/matcher.py` | Shortlisted = no criterion judged `likely_fails`. Every candidate is marked `needs_review`: decision support, never an eligibility determination |
| Queue handling | `app/worker.py` | Result written to `results/v1/<job_id>.json`, then the message is deleted. Any failure leaves the message for retry; after 3 attempts it goes to the dead-letter queue |

Cost guardrails per job: at most `MAX_CANDIDATES` (default 20) patients and `MAX_CRITERIA` (default 5) free-text criteria, so at most 100 model questions.

The worker never calls Bedrock and never logs note text. Raw notes leave it only towards the gateway, inside the cluster.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `QUEUE_URL` | (required) | `ctm-match-jobs` queue URL |
| `RAW_BUCKET` | (required) | patients and notes (synthetic, with planted identifiers) |
| `DATA_BUCKET` | (required) | trials in, results out |
| `GATEWAY_URL` | `http://pii-gateway.pii-gateway` | in-cluster gateway Service |
| `REFERENCE_DATE` | `2026-10-01` | "today" for ages, matching the datasets |
| `MAX_CANDIDATES` / `MAX_CRITERIA` | `20` / `5` | per-job caps |

## Tests

```
docker build --target test -t agent-worker:test services/agent-worker
```

Fake queue, fake S3, fake gateway (plus a real local HTTP server for the client) and a five-patient sample dataset: no AWS, no model, no cost.
