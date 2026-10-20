"""A tiny synthetic dataset in the same shapes as trials/v1, patients/v1 and notes/v1."""

from app.data import Dataset

CRITERIA = """Inclusion Criteria:
* Adults aged 18 to 75 years
* Diagnosed with type 2 diabetes for at least 6 months
Exclusion Criteria:
* History of uncontrolled hypertension
* Current insulin therapy
* Female participants who are pregnant
"""

TRIAL = {"nct_id": "NCT00000001", "title": "Demo diabetes trial", "matched_condition": "type 2 diabetes",
         "sex": "ALL", "minimum_age_years": 18, "maximum_age_years": 75, "eligibility_criteria": CRITERIA}

PATIENTS_CSV = """Id,BIRTHDATE,DEATHDATE,GENDER
p-ok-1,1970-05-01,,F
p-ok-2,1980-01-15,,M
p-too-old,1940-03-03,,M
p-no-diabetes,1975-07-07,,F
p-dead,1965-01-01,2020-01-01,M
"""

CONDITIONS_CSV = """START,STOP,PATIENT,DESCRIPTION
2015-01-01,,p-ok-1,Diabetes mellitus type 2 (disorder)
2016-01-01,,p-ok-2,Diabetes mellitus type 2 (disorder)
2010-01-01,,p-too-old,Diabetes mellitus type 2 (disorder)
2012-01-01,2013-01-01,p-no-diabetes,Diabetes mellitus type 2 (disorder)
2012-01-01,,p-no-diabetes,Essential hypertension (disorder)
2010-01-01,,p-dead,Diabetes mellitus type 2 (disorder)
"""

NOTES_JSONL = "\n".join([
    '{"note_id": "n1", "patient_id": "p-ok-1", "text": "Seen Jane Doe. BP 128/82. Metformin."}',
    '{"note_id": "n2", "patient_id": "p-ok-2", "text": "Seen John Roe. BP 182/110, poorly controlled."}',
    '{"note_id": "n3", "patient_id": "p-too-old", "text": "Seen Old Man."}',
    '{"note_id": "n4", "patient_id": "p-no-diabetes", "text": "Seen Ann Lee."}',
    '{"note_id": "n5", "patient_id": "p-dead", "text": "Historic note."}',
])


def dataset() -> Dataset:
    import json
    return Dataset.from_text(json.dumps(TRIAL), PATIENTS_CSV, CONDITIONS_CSV, NOTES_JSONL)


class FakeGateway:
    """Answers by rule and records what it was sent."""

    def __init__(self, fail_on: str | None = None, refuse_on: str | None = None):
        self.calls, self.fail_on, self.refuse_on = [], fail_on, refuse_on

    def assess(self, note: str, criterion: str) -> dict:
        self.calls.append((note, criterion))
        if self.refuse_on and self.refuse_on in note:
            return {"verdict": "refused", "reason": "stopped"}
        if self.fail_on and self.fail_on in note and "hypertension" in criterion:
            return {"verdict": "likely_fails", "reason": "BP 182/110, poorly controlled."}
        return {"verdict": "likely_meets", "reason": "Nothing in the note against it."}
