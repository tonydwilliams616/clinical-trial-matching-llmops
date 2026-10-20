import datetime

from app import hard
from app.criteria import as_question, select_free_text, split_criteria
from tests.sample import CRITERIA

REF = datetime.date(2026, 10, 1)


def test_age_counts_birthdays_correctly():
    assert hard.age_years("1970-10-01", REF) == 56
    assert hard.age_years("1970-10-02", REF) == 55


def test_sex_rules():
    assert hard.sex_ok("ALL", "M") and hard.sex_ok(None, "F")
    assert hard.sex_ok("FEMALE", "F") and not hard.sex_ok("FEMALE", "M")


def test_diagnosis_must_be_active_and_match():
    assert hard.has_diagnosis(["Diabetes mellitus type 2 (disorder)"], "type 2 diabetes")
    assert not hard.has_diagnosis(["Essential hypertension (disorder)"], "type 2 diabetes")
    assert hard.has_diagnosis(["Chronic kidney disease stage 3 (disorder)"], "chronic kidney disease")


def test_hard_check_explains_failures():
    trial = {"matched_condition": "type 2 diabetes", "sex": "ALL", "minimum_age_years": 18, "maximum_age_years": 75}
    ok, reasons = hard.check(trial, {"BIRTHDATE": "1940-03-03", "GENDER": "M"},
                             ["Diabetes mellitus type 2 (disorder)"], REF)
    assert not ok and any("outside" in r for r in reasons)


def test_split_finds_inclusion_and_exclusion_bullets():
    items = split_criteria(CRITERIA)
    assert [i["kind"] for i in items] == ["inclusion", "inclusion", "exclusion", "exclusion", "exclusion"]


def test_selection_skips_age_and_sex_and_puts_exclusions_first():
    chosen = select_free_text(split_criteria(CRITERIA), limit=5)
    texts = [c["text"] for c in chosen]
    assert "Adults aged 18 to 75 years" not in texts               # age: checked in code
    assert "Female participants who are pregnant" not in texts      # sex: checked in code
    assert chosen[0]["kind"] == "exclusion"
    assert len(select_free_text(split_criteria(CRITERIA), limit=1)) == 1


def test_exclusions_become_must_not_questions():
    assert as_question({"kind": "exclusion", "text": "Current insulin therapy"}) == "Must NOT have: Current insulin therapy"
    assert as_question({"kind": "inclusion", "text": "Has X"}) == "Has X"
