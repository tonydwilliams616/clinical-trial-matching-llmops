# clinical-trial-matching-llmops

**A production-style LLMOps platform on Amazon EKS that shortlists synthetic patients for clinical trials – routing every piece of clinical text through an in-cluster PII-masking gateway before it reaches Amazon Bedrock.**

> Portfolio project, work in progress. The focus is the platform: infrastructure as code, GitOps delivery, keyless workload identity, network-enforced data protection, autoscaling and observability. Built on the patterns from [PitchVision](https://github.com/tonydwilliams616/pitchvision-mlops).

## Ground rules

- **Synthetic data only.** Patients come from Synthea, trial criteria from ClinicalTrials.gov, and clinical notes are generated with planted fake identifiers. No real patient data is ever used.
- **Mask before any LLM – enforced by the network.** Only the PII gateway may reach Bedrock (NetworkPolicies + private VPC endpoints). Masking quality is measured against a labelled benchmark and gated in CI.
- **Decision support, not decisions.** The output is a shortlist with reasons for a human to review, never an eligibility verdict.
- **Rules in code, judgement in the LLM.** Age, sex and confirmed diagnoses are checked in code; the LLM handles free-text criteria.
- **Honest claims.** Designed with HIPAA-aligned controls. This project is not HIPAA-compliant and makes no such claim.

## Target architecture

| Layer | What runs there |
| --- | --- |
| **Infrastructure** | Terraform stacks: account guardrails, data (KMS-encrypted raw / de-identified buckets), registry, network with private endpoints, NAT, EKS, platform add-ons, Bedrock (inference profiles, guardrail, invocation logging) |
| **Delivery** | GitHub Actions with OIDC (no stored AWS keys): blocking Checkov, plan on PR, approval-gated apply, images tagged by commit SHA; Argo CD for everything in the cluster |
| **Security** | PII gateway (Presidio) as the only route to Bedrock; NetworkPolicies; EKS Pod Identity; External Secrets; per-dataset KMS and bucket policies |
| **Workloads** | Agent workers consuming SQS, scaled by KEDA (to zero when idle) on Karpenter spot nodes; HPA, PDBs and AZ spread for resilience |
| **Observability** | OpenTelemetry traces (model, tokens, latency per request), Prometheus + Grafana (p50/p95 latency, throttles, queue depth, cost per request), SLO and cost alerts |

## Phases

| Phase | Focus | Status |
| --- | --- | --- |
| 1 | Foundations: repo, bootstrap, CI/CD, guardrails, data stack, versioned datasets, PII gateway + benchmark gate | In progress |
| 2 | Platform on EKS: network + private endpoints, NAT, cluster, Karpenter, Argo CD | Planned |
| 3 | Bedrock as code, gateway on EKS, SQS + KEDA agent workers | Planned |
| 4 | Observability and resilience: OpenTelemetry, Prometheus/Grafana, SLOs, load and chaos tests | Planned |

## Datasets (built in phase 1)

| Dataset | Bucket | What |
| --- | --- | --- |
| `patients/v1` | raw (KMS) | 1,000 living synthetic adults from Synthea v4.0.0 – reproducible byte for byte |
| `trials/v1` | de-identified | Snapshot of 30 recruiting trials; investigator contact details dropped at fetch |
| `notes/v1` | raw (KMS) | 500 clinical notes with 7,283 planted identifiers and an exact answer key – the gateway's benchmark |

Every dataset has a manifest (parameters, source, per-file SHA-256) and versions are never overwritten.

## Repository layout

```
terraform/
  bootstrap/        # state bucket, GitHub OIDC roles (applied once by an admin)
  modules/          # cost-guardrails
  stacks/           # 00-account, 18-data, ...
scripts/
  data/             # dataset generation and snapshot scripts
.github/workflows/  # Terraform CI/deploy
```
