import datetime

from app.matcher import run_job
from tests.sample import FakeGateway, dataset

REF = datetime.date(2026, 10, 1)
JOB = {"job_id": "demo-001", "nct_id": "NCT00000001"}


def run(gateway, **limits):
    return run_job(JOB, dataset(), gateway, reference=REF,
                   max_candidates=limits.get("max_candidates", 20), max_criteria=limits.get("max_criteria", 5))


def test_hard_criteria_screen_before_any_model_question():
    gateway = FakeGateway()
    result = run(gateway)
    assessed = {c["patient_id"] for c in result["candidates"]}
    assert assessed == {"p-ok-1", "p-ok-2"}                 # too old, no active diagnosis, deceased: out
    assert result["counts"]["failed_hard_criteria"] == 2
    assert all("Seen Old Man." != note for note, _ in gateway.calls)


def test_likely_fails_drops_from_shortlist_but_stays_in_results():
    result = run(FakeGateway(fail_on="182/110"))
    by_id = {c["patient_id"]: c for c in result["candidates"]}
    assert by_id["p-ok-1"]["status"] == "shortlisted"
    assert by_id["p-ok-2"]["status"] == "not_shortlisted"
    assert result["counts"]["shortlisted"] == 1
    assert result["counts"]["not_shortlisted"] == 1


def test_every_result_is_marked_for_human_review():
    result = run(FakeGateway())
    assert result["decision_support_only"] is True
    assert all(c["needs_review"] for c in result["candidates"])


def test_no_evidence_is_never_shortlisted():
    # Regression from the first EKS run: 12 candidates were "shortlisted" with
    # every answer refused - no evidence against them, but none for them either.
    result = run(FakeGateway(refuse_on="Jane Doe"))
    jane = next(c for c in result["candidates"] if c["patient_id"] == "p-ok-1")
    assert jane["unclear"] == len(result["free_text_criteria"])
    assert jane["status"] == "insufficient_evidence"
    assert result["counts"]["insufficient_evidence"] == 1


def test_status_rules():
    from app.matcher import status_for
    assert status_for(meets=2, fails=0) == "shortlisted"
    assert status_for(meets=3, fails=1) == "not_shortlisted"
    assert status_for(meets=0, fails=0) == "insufficient_evidence"


def test_strongest_candidates_listed_first():
    result = run(FakeGateway(fail_on="182/110"))
    assert [c["status"] for c in result["candidates"]] == ["shortlisted", "not_shortlisted"]


def test_caps_bound_the_number_of_model_questions():
    gateway = FakeGateway()
    result = run(gateway, max_candidates=1, max_criteria=1)
    assert result["counts"]["model_questions"] == 1 and len(gateway.calls) == 1


def test_unknown_trial_fails_the_job():
    try:
        run_job({"job_id": "x", "nct_id": "NCT99999999"}, dataset(), FakeGateway(),
                reference=REF, max_candidates=20, max_criteria=5)
    except KeyError:
        return
    raise AssertionError("expected KeyError")
