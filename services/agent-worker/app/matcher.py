"""
One match job: shortlist synthetic patients for one trial, with reasons.

    1. hard criteria in code (hard.py)        - exact, free
    2. free-text criteria via the PII gateway  - masked, then the model
    3. shortlist = no free-text criterion judged "likely_fails"

Everything in the result is a suggestion for human review - never an
eligibility decision. Candidate and criterion caps keep each job's model
spend small and predictable.
"""

import datetime
from concurrent.futures import ThreadPoolExecutor

from . import hard
from .criteria import as_question, select_free_text, split_criteria


def run_job(job: dict, data, gateway, *, reference: datetime.date,
            max_candidates: int, max_criteria: int, parallel: int = 4) -> dict:
    trial = data.trial(job["nct_id"])  # KeyError for an unknown trial: the job fails and is retried / dead-lettered
    questions = [as_question(i) for i in
                 select_free_text(split_criteria(trial.get("eligibility_criteria", "")), max_criteria)]

    # 1. Hard criteria for every patient with a note, in a fixed order (repeatable runs)
    passed, screened_out = [], 0
    for pid in sorted(data.patient_ids_with_notes()):
        ok, reasons = hard.check(trial, data.patient(pid), data.active_conditions(pid), reference)
        if ok:
            passed.append((pid, reasons))
        else:
            screened_out += 1
    candidates = passed[:max_candidates]

    # 2. Free-text criteria through the gateway, a few calls at a time
    pairs = [(pid, q) for pid, _ in candidates for q in questions]
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        verdicts = list(pool.map(lambda pair: gateway.assess(data.note(pair[0]), pair[1]), pairs))
    by_patient: dict[str, list] = {pid: [] for pid, _ in candidates}
    for (pid, question), verdict in zip(pairs, verdicts):
        by_patient[pid].append({"criterion": question, **verdict})

    # 3. Shortlist: nothing judged likely to fail. "unclear" stays in, flagged for review.
    results = []
    for pid, hard_reasons in candidates:
        assessments = by_patient[pid]
        verdict_list = [a["verdict"] for a in assessments]
        results.append({
            "patient_id": pid,
            "shortlisted": "likely_fails" not in verdict_list,
            "needs_review": True,
            "unclear": verdict_list.count("unclear") + verdict_list.count("refused"),
            "hard_criteria": hard_reasons,
            "free_text_criteria": assessments,
        })

    return {
        "job_id": job["job_id"],
        "nct_id": job["nct_id"],
        "title": trial.get("title"),
        "decision_support_only": True,
        "note": "Suggestions for human review. Not an eligibility determination.",
        "reference_date": reference.isoformat(),
        "counts": {
            "patients_screened": screened_out + len(passed),
            "failed_hard_criteria": screened_out,
            "passed_hard_criteria": len(passed),
            "assessed": len(candidates),
            "shortlisted": sum(r["shortlisted"] for r in results),
            "model_questions": len(pairs),
        },
        "free_text_criteria": questions,
        "candidates": results,
    }
