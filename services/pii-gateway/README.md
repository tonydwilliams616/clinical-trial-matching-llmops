# pii-gateway

The only workload allowed to send text to an LLM. It finds identifiers in clinical text and replaces them with labels before anything leaves our environment:

```
"Patient: John Smith  MRN 4821937"  ->  "Patient: <PERSON>  MRN <MRN>"
```

Built with FastAPI and [Presidio](https://microsoft.github.io/presidio/) (spaCy `en_core_web_lg` for names, places and dates; regular expressions for phones, emails, SSNs, MRNs, ZIPs and street addresses). Synthetic data only.

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Liveness: the process is up |
| `GET /readyz` | Readiness: the model is loaded |
| `POST /v1/mask` | `{"text": "..."}` -> masked text, findings (label, position, score - never values), counts |

Request text is never logged. Logs are JSON with sizes, counts and timings only.

## Run locally

```
docker build --target test -t pii-gateway:test . && docker build -t pii-gateway:local . && docker run --rm -p 8080:8080 pii-gateway:local
```

Then, from another terminal:

```
curl -s localhost:8080/v1/mask -H 'content-type: application/json' -d '{"text":"Seen John Smith, MRN 4821937, phone (617) 555-0147."}'
```

## Images

`.github/workflows/pii-gateway-image.yml` runs the tests inside the image build on every PR, and on `main` pushes the runtime image to ECR `ctm/pii-gateway`, tagged with the commit SHA (tags are immutable).

How well it masks is measured, not assumed: PR 11 scores it against the `notes/v1` answer key and fails the build below a recall threshold.
