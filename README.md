# clinical-trial-matching-llmops

**An LLMOps platform on AWS that shortlists synthetic patients for clinical trials** – with de-identification measured before any data reaches an LLM, hard eligibility rules checked in code, and every shortlist explained for human review.

> Portfolio project, work in progress. Built on the patterns from [PitchVision](https://github.com/tonydwilliams616/pitchvision-mlops): Terraform stacks, GitHub Actions with OIDC, Argo CD, Karpenter, MLflow.

## Ground rules

- **Synthetic data only.** Patients come from Synthea, trial criteria from ClinicalTrials.gov, and clinical notes are generated with planted fake identifiers. No real patient data is ever used.
- **De-identify first, and measure it.** Identifiers are removed inside this AWS account before any text reaches an LLM, and the catch rate is reported per identifier type.
- **Decision support, not decisions.** The output is a shortlist with reasons for a human to review, never an eligibility verdict.
- **Rules in code, judgement in the LLM.** Age, sex and confirmed diagnoses are checked in code; the LLM handles free-text criteria.
- **Honest claims.** Designed with HIPAA-aligned controls. This project is not HIPAA-compliant and makes no such claim.

## Phases

| Phase | Focus | Status |
| --- | --- | --- |
| 1 | Synthetic data and de-identification | In progress |
| 2 | Retrieval (pgvector) | Planned |
| 3 | Matching agent (Bedrock, with fallback) | Planned |
| 4 | Evaluation and observability | Planned |
| 5 | Scale and async (queue, KEDA, local GPU model) | Planned |

## Repository layout (planned)

```
terraform/
  bootstrap/        # state bucket, GitHub OIDC roles (applied once by an admin)
  modules/          # cost-guardrails
  stacks/           # 00-account, 18-data, ...
scripts/
  data/             # Synthea generation, ClinicalTrials.gov fetch, note generation
deid/               # de-identification and its evaluation
.github/workflows/  # Terraform CI/deploy, tests
```
