"""
Hard criteria, checked in code - exact, free, and never sent to a model.

    age    from the patient's birth date, as of the dataset's fixed reference date
    sex    the trial's ALL / FEMALE / MALE against the patient's recorded sex
    diagnosis  the trial's condition must be an ACTIVE diagnosis in the record

Pure functions over plain values, so they are easy to test.
"""

import datetime

# Trial search term (trials/v1 matched_condition) -> words that identify the
# matching Synthea diagnosis description, e.g. "Essential hypertension (disorder)".
DIAGNOSIS_TERMS = {
    "type 2 diabetes": ["diabetes mellitus type 2"],
    "hypertension": ["essential hypertension"],
    "chronic kidney disease": ["chronic kidney disease"],
    "hyperlipidemia": ["hyperlipidemia"],
}


def age_years(birthdate: str, reference: datetime.date) -> int:
    born = datetime.date.fromisoformat(birthdate[:10])
    return reference.year - born.year - ((reference.month, reference.day) < (born.month, born.day))


def sex_ok(trial_sex: str | None, patient_gender: str) -> bool:
    wanted = (trial_sex or "ALL").upper()
    return wanted == "ALL" or wanted == {"F": "FEMALE", "M": "MALE"}.get(patient_gender.upper())


def has_diagnosis(active_conditions: list[str], matched_condition: str) -> bool:
    terms = DIAGNOSIS_TERMS.get(matched_condition.lower(), [matched_condition.lower()])
    return any(term in c.lower() for c in active_conditions for term in terms)


def check(trial: dict, patient: dict, active_conditions: list[str],
          reference: datetime.date) -> tuple[bool, list[str]]:
    """(passes, reasons) - every reason is a plain sentence for the reviewer."""
    reasons, passes = [], True
    age = age_years(patient["BIRTHDATE"], reference)
    low, high = trial.get("minimum_age_years"), trial.get("maximum_age_years")
    if (low is not None and age < low) or (high is not None and age > high):
        passes = False
        reasons.append(f"Age {age} is outside {low if low is not None else 'any'}-{high if high is not None else 'any'}.")
    else:
        reasons.append(f"Age {age} is within range.")
    if not sex_ok(trial.get("sex"), patient["GENDER"]):
        passes = False
        reasons.append(f"Trial is for {trial.get('sex')} participants.")
    if not has_diagnosis(active_conditions, trial["matched_condition"]):
        passes = False
        reasons.append(f"No active diagnosis of {trial['matched_condition']}.")
    else:
        reasons.append(f"Active diagnosis of {trial['matched_condition']} recorded.")
    return passes, reasons
