"""
One match job: shortlist synthetic patients for one trial, with reasons.

    1. hard criteria in code (hard.py)        - exact, free
    2. free-text criteria via the PII gateway  - masked, then the model
    3. sort each candidate into one of three groups:
         shortlisted            - no criterion likely failed, and at least one likely met
         not_shortlisted        - at least one criterion likely failed
         insufficient_evidence  - nothing failed, but nothing was confirmed either
                                  (every answer unclear or refused): a person must look

Everything in the result is a suggestion for human review - never an
eligibility decision. Candidate and criterion caps keep each job's model
spend small and predictable.
"""

import contextvars
import datetime
from concurrent.futures import ThreadPoolExecutor

from . import hard
from .criteria import as_question, select_free_text, split_criteria


def status_for(meets: int, fails: int) -> str:
    if fails:
        return "not_shortlisted"
    return "shortlisted" if meets else "insufficient_evidence"


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
    # Pool threads start with an empty context, which would drop the job's
    # trace: each gateway call became its own trace on EKS. Run every call in a
    # copy of this thread's context so its span stays inside the job's trace.
    job_context = contextvars.copy_context()

    def ask(pair):
        return gateway.assess(data.note(pair[0]), pair[1])

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        verdicts = list(pool.map(lambda pair: job_context.copy().run(ask, pair), pairs))
    by_patient: dict[str, list] = {pid: [] for pid, _ in candidates}
    for (pid, question), verdict in zip(pairs, verdicts):
        by_patient[pid].append({"criterion": question, **verdict})

    # 3. Three groups. "No evidence against" is not the same as "evidence for":
    #    a candidate whose every answer was unclear or refused is never shortlisted.
    results = []
    for pid, hard_reasons in candidates:
        assessments = by_patient[pid]
        verdict_list = [a["verdict"] for a in assessments]
        meets, fails = verdict_list.count("likely_meets"), verdict_list.count("likely_fails")
        results.append({
            "patient_id": pid,
            "status": status_for(meets, fails),
            "needs_review": True,
            "meets": meets,
            "fails": fails,
            "unclear": verdict_list.count("unclear") + verdict_list.count("refused"),
            "hard_criteria": hard_reasons,
            "free_text_criteria": assessments,
        })
    # Strongest candidates first: shortlisted by most criteria met, then the rest
    order = {"shortlisted": 0, "insufficient_evidence": 1, "not_shortlisted": 2}
    results.sort(key=lambda r: (order[r["status"]], -r["meets"], r["patient_id"]))

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
            "shortlisted": sum(r["status"] == "shortlisted" for r in results),
            "not_shortlisted": sum(r["status"] == "not_shortlisted" for r in results),
            "insufficient_evidence": sum(r["status"] == "insufficient_evidence" for r in results),
            "model_questions": len(pairs),
        },
        "free_text_criteria": questions,
        "candidates": results,
    }
